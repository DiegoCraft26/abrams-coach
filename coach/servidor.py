"""Servidor local: panel para el monitor secundario + API de estado."""
import json, os, threading, time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from coach import estado_guardado

AQUI = os.path.dirname(os.path.abspath(__file__))

# El panel web se retiró el 2026-11-07: hay una sola interfaz, la nativa (GTK4). El
# servidor queda como API local para el panel y para scripts.
AVISO_RAIZ = ("Abrams Coach: la interfaz es la app nativa.\n"
              "Abre el panel con: abrams-coach demo   (o  abrams-coach jugar)\n"
              "Estado en JSON: /api/estado   ·   Diagnóstico: /api/revisar\n")

# Cuántos segundos sin publicar antes de avisar que los datos están viejos.
# run.py lo sube según --intervalo: con intervalo 10 s, 8 s fijos marcaban
# "congelado" en cada ciclo aunque todo funcionara.
UMBRAL_RANCIO_S = 8.0

class Estado:
    def __init__(self):
        self.lock = threading.Lock()
        self.ultimo = {"listo": False, "mensaje": "esperando datos"}
        self.version = 0
        self.oyentes = []
        self.manual_ts = 0.0   # última inyección manual: pausa el modo demo
        self.ts = 0.0          # cuándo se publicó lo último
        self._firma = None     # contenido del último estado (para detectar congelado)
        # Para el diagnóstico de /api/revisar: cuántas publicaciones hubo y los
        # últimos avisos de fallo, tal como los publicó el bucle.
        self.desde = time.time()
        self.publicaciones = 0
        self.avisos = deque(maxlen=20)

    def publicar(self, datos):
        with self.lock:
            self.ultimo = datos
            self.version += 1
            self.publicaciones += 1
            # `ts` solo avanza si el contenido cambia. El bucle republica el mismo
            # estado cada pocos segundos; sin esto, una partida terminada seguía
            # pareciendo fresca (edad 1 s) con el reloj congelado en 34:32.
            firma = None
            if isinstance(datos, dict):
                firma = (datos.get("t"), datos.get("oro"), datos.get("almas"),
                         (datos.get("estado") or {}).get("estado"))
            if firma is None or firma != self._firma or not datos.get("t"):
                self._firma = firma
                self.ts = time.time()
            # Respaldo en disco: si el coach se cae, el panel aún puede enseñar el
            # último estado con su edad en vez de «sin respuesta».
            estado_guardado.guardar(datos)
            if isinstance(datos, dict) and datos.get("listo") is False:
                self.avisos.append({"ts": round(time.time(), 1),
                                    "mensaje": str(datos.get("mensaje") or "")[:200]})

    def leer(self):
        with self.lock:
            return self.ultimo, self.version

    def encuesta(self):
        """Payload, versión y edad bajo el MISMO lock.

        Con dos llamadas separadas (`leer` y `edad_s`) una publicación en medio empareja
        el payload viejo con edad 0 y dice "fresco" justo cuando no lo está.
        """
        with self.lock:
            edad = (time.time() - self.ts) if self.ts else None
            return self.ultimo, self.version, edad

    def edad_s(self):
        """Segundos desde la última publicación.

        Sin esto el panel seguía diciendo "en vivo" con datos de hace minutos: si el
        stream se cortaba o la partida terminaba, se mostraba una compra vieja como si
        fuera actual (detectado por QA de UI, 2026-11-07).
        """
        with self.lock:
            return (time.time() - self.ts) if self.ts else None

EST = Estado()


# --- diagnóstico del botón "Revisar" -------------------------------------------
# Solo un diagnóstico a la vez: cada uno hace dos golpes a la API (con la puerta de
# 3 s de coach.en_vivo) y puede pedir una respuesta al modelo.
_LOCK_REVISION = threading.Lock()

SISTEMA_REVISION = (
    "Diagnosticas la conexión del coach de Deadlock. Recibes un JSON con el estado "
    "real: fuente de datos, edad de lo último publicado, último tick, avisos y errores "
    "acumulados, cuota de la API y si el match sigue activo.\n"
    "Responde en español, en 3 a 5 líneas, sin adornos: qué está roto, qué NO está "
    "roto y qué hacer ahora. No inventes números que no estén en el JSON; si falta un "
    "dato, escribe \"sin medir\". No propongas tocar el juego ni reiniciar procesos.")


def diagnostico():
    """Lo que se sabe del coach ahora mismo, sin adornos y sin inventar.

    Lo que no se pudo medir queda en None (el que llama lo muestra como "sin medir").
    """
    datos, _, edad = EST.encuesta()
    datos = datos if isinstance(datos, dict) else {}
    from coach import en_vivo

    red = en_vivo.DIARIO.resumen()
    try:
        from coach.fuentes import api_vivo
        buscado = api_vivo.estado()
    except Exception as exc:                                   # noqa: BLE001
        api_vivo, buscado = None, {}
        en_vivo.DIARIO.error(f"revisar: {type(exc).__name__}: {exc}")
    match = red.get("match") or buscado.get("match")
    diag = {
        "ts": round(time.time(), 1),
        "fuente": datos.get("fuente"),
        "listo": datos.get("listo"),
        "mensaje": datos.get("mensaje"),
        "edad_datos_s": round(edad, 1) if edad is not None else None,
        "rancio": bool(edad is not None and edad > UMBRAL_RANCIO_S),
        "ultimo_t": datos.get("t"),
        "publicaciones": EST.publicaciones,
        "segundos_arriba": round(time.time() - EST.desde),
        "avisos": list(EST.avisos)[-5:],
        "red": red,
        "cuota_pausa_s": round(en_vivo.pausa_restante_s()),
        "descubrimiento": {
            "via": buscado.get("via"),
            "detalle": buscado.get("detalle"),
            "edad_s": (round(time.time() - buscado["ts"], 1)
                       if buscado.get("ts") else None),
        },
        "match": None,
    }
    if match and api_vivo is not None:
        diag["match"] = api_vivo.existe_match(match)
    return diag


def _contenido(respuesta):
    """Texto de la primera opción de un `chat/completions`, o None."""
    try:
        mensaje = respuesta["choices"][0]["message"]
        return (mensaje.get("content") or "").strip() or None
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def veredicto(diag, timeout_s=20.0):
    """Pide un veredicto en texto a DS 4.1 Flash sobre el diagnóstico.

    Si no hay clave o el modelo falla, devuelve el motivo y ningún texto: nada de
    inventar un veredicto.
    """
    try:
        from coach.agente.proveedor import ErrorProveedor, proveedor_flash
    except Exception as exc:                                   # noqa: BLE001
        return {"texto": None, "modelo": None, "proveedor": None,
                "motivo": f"no se pudo cargar el proveedor: {type(exc).__name__}: {exc}"}
    prov = proveedor_flash()
    if prov is None:
        return {"texto": None, "modelo": None, "proveedor": None,
                "motivo": "no hay proveedor de DS 4.1 Flash configurado"}
    if not prov.hay_clave():
        return {"texto": None, "modelo": prov.modelo, "proveedor": prov.nombre,
                "motivo": (f"falta la clave {prov.clave_env}: no está en el entorno "
                           "ni en ~/.config/abrams-coach/credenciales.yaml")}
    mensajes = [{"role": "system", "content": SISTEMA_REVISION},
                {"role": "user", "content": json.dumps(diag, ensure_ascii=False)}]
    try:
        respuesta = prov.chat(mensajes, timeout_s=timeout_s)
    except ErrorProveedor as exc:
        return {"texto": None, "modelo": prov.modelo, "proveedor": prov.nombre,
                "motivo": str(exc)}
    except Exception as exc:                                   # noqa: BLE001
        return {"texto": None, "modelo": prov.modelo, "proveedor": prov.nombre,
                "motivo": f"{type(exc).__name__}: {exc}"}
    texto = _contenido(respuesta)
    if not texto:
        return {"texto": None, "modelo": prov.modelo, "proveedor": prov.nombre,
                "motivo": "el modelo no devolvió texto"}
    return {"texto": texto, "modelo": prov.modelo, "proveedor": prov.nombre,
            "motivo": None}



class Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _enviar(self, codigo, cuerpo, tipo="application/json; charset=utf-8"):
        if isinstance(cuerpo, (dict, list)):
            cuerpo = json.dumps(cuerpo, ensure_ascii=False).encode()
        elif isinstance(cuerpo, str):
            cuerpo = cuerpo.encode()
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        ruta = urlparse(self.path).path
        if ruta in ("/", "/index.html"):
            self._enviar(200, AVISO_RAIZ, "text/plain; charset=utf-8")
        elif ruta == "/api/estado":
            datos, _, edad = EST.encuesta()
            if EST.ts == 0:
                # El coach arrancó y todavía no publicó nada: se sirve lo último que
                # quedó en disco, con su edad real y diciendo que viene de ahí.
                respaldo = estado_guardado.como_respaldo()
                if respaldo is not None:
                    datos = respaldo
                    edad = respaldo.get("edad_s")
            if isinstance(datos, dict):
                datos = dict(datos)
                datos["edad_s"] = round(edad, 1) if edad is not None else None
                datos["rancio"] = bool(edad is not None and edad > UMBRAL_RANCIO_S)
            self._enviar(200, datos)
        elif ruta == "/api/vision":
            # Lo que la visión sabe, sin imágenes ni claves: inventario con su edad y el
            # estado de la cola (cuántos cuadros van, cuántos fallaron, si se agotó).
            from coach import inventario_propio
            from coach.agente import vision_cola
            self._enviar(200, {"inventario": inventario_propio.estado(),
                               "cola": vision_cola.estado()})
        elif ruta.startswith("/icono/"):
            iid = ruta.split("/")[-1].replace(".webp", "").replace(".png", "")
            if not iid.isdigit():
                self._enviar(404, {"error": "id inválido"})
                return
            base = os.path.join(os.path.dirname(AQUI), "data", "iconos", "items")
            for ext, tipo in ((".webp", "image/webp"), (".png", "image/png")):
                ruta_icono = os.path.join(base, iid + ext)
                if os.path.exists(ruta_icono):
                    with open(ruta_icono, "rb") as f:
                        self._enviar(200, f.read(), tipo)
                    return
            self._enviar(404, {"error": "sin icono"})
        elif ruta.startswith("/icono-heroe/"):
            nombre = ruta.split("/")[-1].replace(".webp", "").replace(".png", "")
            if not nombre or "/" in nombre or ".." in nombre:
                self._enviar(404, {"error": "nombre inválido"})
                return
            base = os.path.join(os.path.dirname(AQUI), "data", "iconos", "heroes")
            for ext, tipo in ((".webp", "image/webp"), (".png", "image/png")):
                ruta_icono = os.path.join(base, nombre + ext)
                if os.path.exists(ruta_icono):
                    with open(ruta_icono, "rb") as f:
                        self._enviar(200, f.read(), tipo)
                    return
            self._enviar(404, {"error": "sin icono"})
        elif ruta == "/api/salud":
            self._enviar(200, {"ok": True, "ts": time.time()})
        elif ruta == "/api/revisar":
            # `?modelo=0` devuelve solo el diagnóstico crudo, sin gastar una llamada
            # al modelo (para scripts y para cuando la clave no está).
            sin_modelo = parse_qs(urlparse(self.path).query).get("modelo", ["1"])[0] in (
                "0", "no", "false", "off")
            with _LOCK_REVISION:
                diag = diagnostico()
                salida = {"ok": True, "diagnostico": diag}
                if sin_modelo:
                    salida.update({"texto": None, "modelo": None, "proveedor": None,
                                   "motivo": "pedido sin modelo (?modelo=0)"})
                else:
                    salida.update(veredicto(diag))
            self._enviar(200, salida)
        elif ruta == "/eventos":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            vistos = -1
            try:
                while True:
                    datos, v = EST.leer()
                    if v != vistos:
                        vistos = v
                        payload = json.dumps(datos, ensure_ascii=False)
                        self.wfile.write(f"data: {payload}\n\n".encode())
                        self.wfile.flush()
                    else:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    time.sleep(0.7)
            except (BrokenPipeError, ConnectionResetError):
                return
        else:
            self._enviar(404, {"error": "no existe"})

    def do_POST(self):
        ruta = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        cuerpo = self.rfile.read(n) if n else b"{}"
        if ruta == "/api/simular":
            analizador = getattr(self.server, "analizador", None)
            if analizador is None:
                self._enviar(503, {"error": "motor no cargado"})
                return
            try:
                estado = json.loads(cuerpo or b"{}")
                EST.manual_ts = time.time()
                salida = analizador(estado)
                # Gancho de depuración: permite inyectar el bloque `latencia` para
                # revisar cómo se ve el pie sin tener una partida real corriendo.
                if isinstance(estado, dict) and isinstance(estado.get("latencia"), dict):
                    salida["latencia"] = estado["latencia"]
                EST.publicar(salida)
                self._enviar(200, {"ok": True})
            except Exception as e:
                self._enviar(400, {"error": str(e)})
        else:
            self._enviar(404, {"error": "no existe"})


def arrancar(puerto=8090, analizador=None):
    srv = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    # Sin esto, cada conexión keep-alive deja un hilo esperando y el proceso no termina
    # nunca: el test del servidor se quedaba colgado al salir.
    srv.daemon_threads = True
    srv.analizador = analizador
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    return srv

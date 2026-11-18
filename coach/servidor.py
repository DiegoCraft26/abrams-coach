"""Servidor local: panel para el monitor secundario + API de estado."""
import json, os, threading, time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from coach import estado_guardado

AQUI = os.path.dirname(os.path.abspath(__file__))

# El panel web se retiró el 2026-11-07: hay una sola interfaz, la nativa (GTK4). El
# servidor queda como API local para el panel y para scripts.
AVISO_RAIZ = ("Abrams Coach: el panel web está en /panel (cualquier navegador).\n"
              "Tarjeta mínima 420x160: /tarjeta   ·   Estado: /api/estado   ·   "
              "Diagnóstico: /api/revisar\n")

# Cuántos segundos sin publicar antes de avisar que los datos están viejos.
# run.py lo sube según --intervalo: con intervalo 10 s, 8 s fijos marcaban
# "congelado" en cada ciclo aunque todo funcionara.
UMBRAL_RANCIO_S = 8.0


def estado_publico(datos, edad):
    """Lo que sirve `/api/estado`: la foto con su edad real y la marca de rancio.

    El perfil de riesgo se apaga cuando la foto ya no es de ahora: el motor lo calcula
    para la partida que se está jugando, y un corte histórico de hace medio minuto
    repetido como si fuera vivo es justo lo que el panel no puede hacer. Se apaga aquí
    además de en el panel para que el payload no tenga dos verdades.
    """
    if not isinstance(datos, dict):
        return datos
    datos = dict(datos)
    datos["edad_s"] = round(edad, 1) if edad is not None else None
    rancio = bool(edad is not None and edad > UMBRAL_RANCIO_S)
    datos["rancio"] = rancio
    if rancio:
        datos["riesgo"] = None
    # Sin partida, lo más útil es cómo fue la última: la nota que deja el vigilante al
    # cerrar Deadlock. Se lee aquí y no en el panel para que el navegador no toque disco.
    if datos.get("listo") is False:
        nota, edad_nota = ultima_nota()
        if nota:
            datos["ultima_nota"] = nota
            datos["ultima_nota_edad_s"] = edad_nota
        objetivo = objetivo_sesion()
        if objetivo:
            datos["objetivo"] = objetivo
    return datos


def objetivo_sesion(ruta=None):
    """El objetivo de la sesión (lo escribe `plan.py`), sin red y sin calcular progreso.

    El progreso necesita el historial; aquí solo se publica qué se está persiguiendo para
    que el panel y el overlay lo enseñen antes de la partida. Si el archivo no está, None.
    """
    ruta = ruta or os.path.join(os.path.dirname(AQUI), "salida", "plan_actual.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    regla = doc.get("regla")
    # El 3 200 dejó de ser meta el 2026-11-18 (a escala no separa nada). Un objetivo
    # viejo con esa regla no se publica: sería pedirle al jugador que mueva una aguja
    # que no mueve nada.
    if regla not in ("muertes", "participacion"):
        return None
    etiqueta = {"muertes": f"≤{doc.get('meta', 6)} muertes",
                "participacion": f"≥{doc.get('meta')} k+a/min",
                "min3200": f"3 200 antes del min {doc.get('meta')}"}.get(regla, regla)
    return {"regla": regla, "texto": f"{doc.get('necesarias', 3)} de {doc.get('partidas', 5)} con {etiqueta}",
            "desde": doc.get("desde")}


def ultima_nota(ruta=None, limite_s=86400):
    """Texto de la última nota post-partida, si existe y no es de hace más de un día."""
    import time
    ruta = ruta or os.path.join(os.path.dirname(AQUI), "salida", "ultima_nota.txt")
    try:
        edad = time.time() - os.path.getmtime(ruta)
        if edad > limite_s:
            return None, None
        with open(ruta, encoding="utf-8") as f:
            texto = f.read().strip()
        return (texto[:600] if texto else None), round(edad)
    except OSError:
        return None, None


def _json_default(o):
    """Convierte lo que json no sabe, sin romper el endpoint.

    Un numpy.int64, un set o un deque en el estado hacían fallar `json.dumps` y el
    panel se quedaba en «sin coach»: una pieza de datos rara apagaba la app entera.
    Los escalares numéricos se convierten a su valor (no a texto) para que el JS los
    siga tratando como números.
    """
    item = getattr(o, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:                                  # noqa: BLE001
            pass
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    return str(o)

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
# Los iconos se nombran por id: nunca cambia su contenido, así que se cachean de verdad.
CACHE_ICONO = "public, max-age=604800, immutable"
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

    def _enviar(self, codigo, cuerpo, tipo="application/json; charset=utf-8",
                cache="no-store"):
        """`cache` sólo se relaja para lo que no cambia nunca (los iconos por id)."""
        if isinstance(cuerpo, (dict, list)):
            try:
                texto = json.dumps(cuerpo, ensure_ascii=False, default=_json_default)
            except (TypeError, ValueError):
                # Último recurso: nunca dejar al panel sin respuesta por un dato raro.
                texto = json.dumps({"listo": False,
                                    "mensaje": "el estado no se pudo serializar"},
                                   ensure_ascii=False)
            cuerpo = texto.encode()
        elif isinstance(cuerpo, str):
            cuerpo = cuerpo.encode()
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        ruta = urlparse(self.path).path
        if ruta in ("/", "/index.html"):
            self._enviar(200, AVISO_RAIZ, "text/plain; charset=utf-8")
        elif ruta in ("/panel", "/panel.html"):
            # Panel web servido por el propio coach: mismo dato que la app nativa y
            # ningún proceso extra. Útil también desde otro equipo de la LAN.
            from .ui.web import PAGINA
            self._enviar(200, PAGINA.encode("utf-8"), "text/html; charset=utf-8")
        elif ruta in ("/tarjeta", "/tarjeta.html"):
            # Tarjeta de 420x160 para mirar entre peleas. Se renderiza con el último
            # estado ya dentro: si el navegador tarda en ejecutar el JS, la primera
            # pintura no es un cuadro vacío. El JS la refresca cada segundo.
            from .ui.tarjeta import pagina
            datos, _, edad = EST.encuesta()
            if EST.ts == 0:
                respaldo = estado_guardado.como_respaldo()
                if respaldo is not None:
                    datos = respaldo
                    edad = respaldo.get("edad_s")
            if isinstance(datos, dict):
                datos = dict(datos)
                rancio = bool(datos.get("rancio")) or (
                    edad is not None and edad > UMBRAL_RANCIO_S)
                datos["edad_s"] = round(edad, 1) if edad is not None else None
                datos["rancio"] = rancio
            self._enviar(200, pagina(datos, edad).encode("utf-8"),
                         "text/html; charset=utf-8")
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
                datos = estado_publico(datos, edad)
            self._enviar(200, datos)
        elif ruta == "/api/identidad":
            # Qué partida se cree el coach, por qué vía y qué dice el console.log del
            # juego. Es el endpoint para responder «¿por qué no enganchó mi partida?».
            from coach import telemetria
            from coach.fuentes import api_vivo, log_juego
            try:
                log = {"disponible": log_juego.disponible(), "fase": log_juego.fase(),
                       "heroe": log_juego.heroe(), "match": log_juego.match_id(),
                       "cuenta": log_juego.cuenta()}
            except Exception:                              # noqa: BLE001
                log = {"disponible": False}
            self._enviar(200, {
                "descubrimiento": api_vivo.estado(),
                "console": log,
                "telemetria": telemetria.resumen(),
                "ultimos": telemetria.leer(10),
            })
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
                        # El icono de un id no cambia: cachearlo ahorra 14 peticiones
                        # por segundo en cada repintado del panel.
                        self._enviar(200, f.read(), tipo, cache=CACHE_ICONO)
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
                        self._enviar(200, f.read(), tipo, cache=CACHE_ICONO)
                    return
            self._enviar(404, {"error": "sin icono"})
        elif ruta == "/api/version":
            # ¿La app abierta corre el código que tengo? Ver coach/version.py y
            # docs/VERSION.md. Sirve para no discutir de memoria si falta reiniciar.
            from coach import version
            self._enviar(200, version.comparar())
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
    # Deja escrito con qué código arrancó esta instancia: así /api/version puede
    # decir si la ventana abierta quedó vieja tras una edición. Nunca rompe el arranque.
    try:
        from coach import version
        version.marcar_arranque()
    except Exception:                                    # noqa: BLE001
        pass
    srv = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    # Sin esto, cada conexión keep-alive deja un hilo esperando y el proceso no termina
    # nunca: el test del servidor se quedaba colgado al salir.
    srv.daemon_threads = True
    srv.analizador = analizador
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    return srv

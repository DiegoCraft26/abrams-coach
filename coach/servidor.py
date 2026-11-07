"""Servidor local: panel para el monitor secundario + API de estado."""
import json, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

AQUI = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(AQUI, "ui", "index.html")

# Cuántos segundos sin publicar antes de avisar que los datos están viejos.
# run.py lo sube según --intervalo: con intervalo 10 s, 8 s fijos marcaban
# "congelado" en cada ciclo aunque todo funcionara.
UMBRAL_RANCIO_S = 8.0

# Copiloto: se configura desde run.py (`servidor.configurar_copiloto`). Si no hay
# copiloto, el endpoint responde 503 y el panel esconde el drawer.
COPILOTO = None
TIMEOUT_COPILOTO_S = 75.0


def configurar_copiloto(copiloto):
    global COPILOTO
    COPILOTO = copiloto
    return COPILOTO

class Estado:
    def __init__(self):
        self.lock = threading.Lock()
        self.ultimo = {"listo": False, "mensaje": "esperando datos"}
        self.version = 0
        self.oyentes = []
        self.manual_ts = 0.0   # última inyección manual: pausa el modo demo
        self.ts = 0.0          # cuándo se publicó lo último

    def publicar(self, datos):
        with self.lock:
            self.ultimo = datos
            self.version += 1
            self.ts = time.time()

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
            with open(UI, "rb") as f:
                self._enviar(200, f.read(), "text/html; charset=utf-8")
        elif ruta == "/api/estado":
            datos, _, edad = EST.encuesta()
            if isinstance(datos, dict):
                datos = dict(datos)
                datos["edad_s"] = round(edad, 1) if edad is not None else None
                datos["rancio"] = bool(edad is not None and edad > UMBRAL_RANCIO_S)
            self._enviar(200, datos)
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
        elif ruta == "/api/copiloto":
            self._enviar(200, {
                "disponible": COPILOTO is not None,
                "presupuesto": (COPILOTO.presupuesto.estado() if COPILOTO else None),
            })
        elif ruta == "/api/salud":
            self._enviar(200, {"ok": True, "ts": time.time()})
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
                EST.publicar(analizador(estado))
                self._enviar(200, {"ok": True})
            except Exception as e:
                self._enviar(400, {"error": str(e)})
        elif ruta == "/api/copiloto":
            if COPILOTO is None:
                self._enviar(503, {"error": "copiloto no configurado"})
                return
            try:
                cuerpo = json.loads(cuerpo or b"{}")
            except ValueError:
                cuerpo = {}
            pregunta = str((cuerpo or {}).get("pregunta") or "")[:600]
            if not pregunta.strip():
                self._enviar(400, {"error": "pregunta vacía"})
                return
            # El copiloto puede tardar (varias llamadas al modelo): se ejecuta aparte y
            # se corta con timeout para no colgar el servidor del panel.
            caja = {}

            def _correr():
                try:
                    caja["r"] = COPILOTO.preguntar(pregunta)
                except Exception as exc:                       # noqa: BLE001
                    caja["r"] = {"error": f"{type(exc).__name__}: {exc}"}

            hilo = threading.Thread(target=_correr, daemon=True)
            hilo.start()
            hilo.join(TIMEOUT_COPILOTO_S)
            if hilo.is_alive():
                self._enviar(504, {"error": "el copiloto no respondió a tiempo"})
                return
            self._enviar(200, caja.get("r") or {"error": "sin respuesta"})
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

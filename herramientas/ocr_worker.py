"""Servidor de OCR para delegar la lectura del HUD a otra máquina.

Corre en la PC que NO juega (<pc-auxiliar>) y hace lo único caro del ciclo: tesseract.
El cliente (`coach/fuentes/hud_remoto.py`) le manda los tres recortes ya hechos —reloj,
banda de oro y caja de oro— y aquí se reensamblan en un marco falso para reutilizar
`hud_rapido.leer` tal cual: la misma lógica, el mismo parseo, los mismos umbrales. No hay
una segunda implementación que se pueda desincronizar.

    python3 herramientas/ocr_worker.py --puerto 8092 --host 0.0.0.0

Endpoints:
    GET  /salud   -> versión, si hay tesseract y cuántas lecturas lleva
    POST /leer    -> {"tamano": [w, h], "cajas": {"x0,y0,x1,y1": "<b64 png>"}, ...}
                     -> {"t": segundos, "oro": almas, "ms_reloj", "ms_oro", "ms_total"}

El servidor no captura nada ni ve la pantalla: solo recibe píxeles ya recortados.
"""
import argparse
import base64
import io
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from PIL import Image                                            # noqa: E402

from coach.fuentes import hud_rapido                              # noqa: E402

CUENTAS = {"lecturas": 0, "errores": 0, "desde": time.strftime("%Y-%m-%d %H:%M:%S")}
_LOCK = threading.Lock()


class MarcoRemoto:
    """Marco sin captura: `.crop(caja)` devuelve el recorte que mandó el cliente.

    Se identifica la caja por su tupla exacta de coordenadas, que es la misma que pide
    `hud_rapido.leer` después de escalarla al tamaño del cuadro.
    """

    def __init__(self, tamano, cajas):
        self.size = tuple(tamano)
        self._cajas = cajas          # "x0,y0,x1,y1" -> PIL.Image

    def crop(self, caja):
        clave = ",".join(str(int(v)) for v in caja)
        im = self._cajas.get(clave)
        if im is None:
            raise KeyError(f"el cliente no mandó la caja {clave}")
        return im


def _decodificar(cajas):
    salida = {}
    for clave, b64 in (cajas or {}).items():
        with Image.open(io.BytesIO(base64.b64decode(b64))) as im:
            salida[str(clave)] = im.convert("RGB")
    return salida


class Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, formato, *args):              # no ensuciar el journal
        return

    def _json(self, codigo, cuerpo):
        datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        if self.path.split("?")[0] != "/salud":
            self._json(404, {"error": "no existe"})
            return
        try:
            version = subprocess.run(["tesseract", "--version"], capture_output=True,
                                     text=True, timeout=5).stdout.splitlines()[0]
        except Exception:                                  # noqa: BLE001
            version = None
        with _LOCK:
            cuentas = dict(CUENTAS)
        self._json(200, {"ok": bool(version), "tesseract": version,
                         "cajas_defecto": hud_rapido.CAJAS_DEFECTO,
                         "referencia": list(hud_rapido.REFERENCIA),
                         "cuentas": cuentas})

    def do_POST(self):
        if self.path.split("?")[0] != "/leer":
            self._json(404, {"error": "no existe"})
            return
        t0 = time.perf_counter()
        try:
            largo = int(self.headers.get("Content-Length") or 0)
            if largo <= 0 or largo > 8 * 1024 * 1024:
                self._json(413, {"error": f"cuerpo de {largo} bytes"})
                return
            cuerpo = json.loads(self.rfile.read(largo).decode("utf-8"))
            tamano = cuerpo.get("tamano") or list(hud_rapido.REFERENCIA)
            marco = MarcoRemoto(tamano, _decodificar(cuerpo.get("cajas")))
            salida = hud_rapido.leer(marco, cuerpo.get("cajas_cfg"),
                                     cuerpo.get("color"))
            salida["ms_total"] = round((time.perf_counter() - t0) * 1000, 1)
            salida["ok"] = salida.get("t") is not None or salida.get("oro") is not None
            with _LOCK:
                CUENTAS["lecturas"] += 1
            self._json(200, salida)
        except Exception as exc:                           # noqa: BLE001
            with _LOCK:
                CUENTAS["errores"] += 1
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--puerto", type=int, default=8092)
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.puerto), Manejador)
    print(f"ocr worker en http://{a.host}:{a.puerto} · tesseract "
          f"{'sí' if subprocess.run(['which', 'tesseract'], capture_output=True).returncode == 0 else 'NO'}",
          flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()

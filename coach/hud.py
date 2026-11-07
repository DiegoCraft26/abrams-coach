#!/usr/bin/env python3
"""Lectura en tiempo real del HUD de Deadlock por captura + OCR.

No lee memoria del juego ni usa el API: captura la pantalla con spectacle,
recorta el reloj y las almas, y los lee con tesseract. Es el único camino
para tener la hora y el oro del HUD sin el retraso del broadcast.

Coordenadas para 4480x1440 con el juego a pantalla completa en DP-2
( x=1920..4480 ). Si cambia la resolución o el monitor, hay que recalibrar.
"""
import os
import re
import subprocess
import tempfile
import threading
import time

from PIL import Image, ImageOps

# Reloj arriba al centro y almas abajo a la izquierda, en coordenadas del
# escritorio completo (4480x1440).
CAJA_RELOJ = (3150, 8, 3265, 52)
CAJA_ALMAS = (2050, 1190, 2210, 1260)


_LOCK = threading.Lock()


def _capturar():
    ruta = os.path.join(tempfile.gettempdir(), "abrams-hud.png")
    with _LOCK:
        subprocess.run(["spectacle", "-b", "-n", "-f", "-o", ruta],
                       check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ruta


def _ocr(im, caja, escala, whitelist, psm="7"):
    c = im.crop(caja)
    c = c.resize((c.width * escala, c.height * escala), Image.LANCZOS)
    c = ImageOps.autocontrast(c)
    # texto claro sobre fondo oscuro: se invierte para tesseract
    c = ImageOps.invert(c)
    ruta = os.path.join(tempfile.gettempdir(), "abrams-ocr.png")
    c.save(ruta)
    salida = subprocess.run(
        ["tesseract", ruta, "stdout", "--psm", psm,
         "-c", f"tessedit_char_whitelist={whitelist}"],
        capture_output=True, text=True, timeout=10).stdout
    return salida.strip()


def _oro_amplio(im):
    """El último número de 2+ dígitos del bloque inferior izquierdo es el oro.

    Robusto ante el desplazamiento del HUD: no depende de que el nivel tenga
    uno o dos dígitos, que es lo que corría la caja fija.
    """
    texto = _ocr(im, (1950, 1080, 2450, 1440), 3, "0123456789, ", psm="6")
    numeros = [n for n in re.findall(r"\d[\d,]*", texto)
               if len(n.replace(",", "")) >= 2]
    if not numeros:
        return None
    try:
        return int(numeros[-1].replace(",", ""))
    except ValueError:
        return None


def leer_hud(ruta=None):
    """Devuelve {'t': segundos, 'oro': almas, 'ts': time.time()} o None."""
    if ruta is None:
        try:
            ruta = _capturar()
        except (subprocess.SubprocessError, OSError):
            return None
    try:
        im = Image.open(ruta).convert("L")
    except Exception:
        return None

    reloj = _ocr(im, CAJA_RELOJ, 6, "0123456789:")
    oro = _oro_amplio(im)

    m = re.search(r"(\d{1,2}):(\d{2})", reloj)
    t = int(m.group(1)) * 60 + int(m.group(2)) if m else None

    return {"t": t, "oro": oro, "ts": time.time()}


def leer_match_id(ruta=None):
    """Lee el 'MATCH: 123456789' de la esquina inferior derecha."""
    if ruta is None:
        try:
            ruta = _capturar()
        except (subprocess.SubprocessError, OSError):
            return None
    try:
        im = Image.open(ruta).convert("L")
    except Exception:
        return None
    c = im.crop((4050, 1330, 4480, 1440))
    c = c.resize((c.width * 3, c.height * 3), Image.LANCZOS)
    c = ImageOps.autocontrast(c)
    c = ImageOps.invert(c)
    p = os.path.join(tempfile.gettempdir(), "abrams-match.png")
    c.save(p)
    texto = subprocess.run(
        ["tesseract", p, "stdout", "--psm", "6",
         "-c", "tessedit_char_whitelist=MATCH:0123456789"],
        capture_output=True, text=True, timeout=10).stdout
    m = re.search(r"MATCH:?\s*(\d{6,})", texto)
    return int(m.group(1)) if m else None


if __name__ == "__main__":
    for _ in range(3):
        print(leer_hud(), flush=True)
        time.sleep(1)

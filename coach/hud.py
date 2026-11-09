#!/usr/bin/env python3
"""Lectura del HUD de Deadlock por captura de pantalla + OCR.

No lee memoria del juego ni usa el API: captura la pantalla, recorta el reloj, el oro y
el MATCH, y los lee con tesseract. Es el único camino para tener la hora y el oro del HUD
sin el retraso del broadcast.

La captura es por REGIÓN con KWin (`coach/fuentes/captura_kwin.py`): pedir solo la caja
que se va a leer cuesta 1-3 ms en vez de los 415 ms de un `spectacle -f` de la pantalla
entera. Si KWin no está o no contesta en 300 ms, se cae al método viejo sin más: un cuadro
completo con spectacle del que se recortan las mismas cajas. Además, lo leído se guarda
por caja: si los píxeles de esa caja no cambiaron, no se vuelve a llamar a tesseract.

Coste por lectura, medido el 2026-11-08 en esta máquina (escritorio 4480x1440, juego
cerrado; con partida abierta **sin medir**). Mediana de 5–8 lecturas:

                         antes     ahora
    leer_hud()          916 ms    4 ms si ninguna caja cambió
                                  450 ms si cambiaron las dos (reloj 135 + oro 337)
    leer_match_id()     747 ms    2 ms si el MATCH no cambió · 160 ms si cambió
    capturar la caja    ~415 ms   0.9–2.5 ms

El suelo es tesseract: arrancarlo cuesta ~106 ms en cada invocación y no hay motor en
proceso, así que no se baja de ahí. Lo que se quita es la captura (415 → 2 ms) y el OCR
repetido mientras la caja siga idéntica. Ese «no cambió» es lo normal en el MATCH, que se
queda fijo toda la partida; el reloj, en cambio, cambia cada segundo, así que en vivo lo
habitual es pagar el OCR del reloj (~135 ms) y no el de las dos cajas.
`coach/fuentes/hud_rapido.py`, el camino vivo, sí los lee en paralelo cuando hacen falta.

Coordenadas para 4480x1440 con el juego a pantalla completa en DP-2 ( x=1920..4480 ).
Si cambia la resolución o el monitor, hay que recalibrar.
"""
import os
import re
import subprocess
import tempfile
import threading
import time

from PIL import Image, ImageOps

from .fuentes import captura_kwin

# Reloj arriba al centro, almas abajo a la izquierda y MATCH abajo a la derecha, en
# coordenadas del escritorio completo (4480x1440).
CAJA_RELOJ = (3150, 8, 3265, 52)
CAJA_ALMAS = (2050, 1190, 2210, 1260)
CAJA_ORO = (1950, 1080, 2450, 1440)
# El id va diminuto abajo a la derecha; la caja vieja metía el minimapa y el texto
# "SERVER CPU" y el OCR no sacaba nada. Ajustada el 2026-11-09 sobre un cuadro real.
CAJA_MATCH = (4335, 1390, 4475, 1412)


_LOCK = threading.Lock()
_LEIDOS = {}        # caja -> (píxeles, texto): no repetir OCR si la pantalla no cambió


def _capturar():
    """Método viejo: un cuadro de la pantalla entera a disco con spectacle (~415 ms)."""
    ruta = os.path.join(tempfile.gettempdir(), "abrams-hud.png")
    with _LOCK:
        subprocess.run(["spectacle", "-b", "-n", "-f", "-o", ruta],
                       check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ruta


def _ocr(im, caja, escala, whitelist, psm="7", umbral=100):
    """OCR de una caja del HUD.

    Antes usaba autocontrast + invertir y no leía el id de partida (devolvía vacío o
    basura). Con un umbral duro sobre el brillo el mismo recorte devuelve el número
    exacto: medido con un cuadro real de una ranked en curso.
    """
    c = im.crop(caja).convert("L")
    c = c.resize((c.width * escala, c.height * escala), Image.LANCZOS)
    c = c.point(lambda p: 255 if p > umbral else 0)
    # Archivo ÚNICO por llamada: el reloj y el MATCH se leen desde hilos distintos y con
    # un nombre fijo una hebra pisaba la imagen de la otra.
    fd, ruta = tempfile.mkstemp(prefix="abrams-ocr-", suffix=".png")
    os.close(fd)
    try:
        c.save(ruta)
        salida = subprocess.run(
            ["tesseract", ruta, "stdout", "--psm", psm,
             "-c", f"tessedit_char_whitelist={whitelist}"],
            capture_output=True, text=True, timeout=10).stdout
    finally:
        try:
            os.unlink(ruta)
        except OSError:
            pass
    return salida.strip()


class _Cajas:
    """Cajas del HUD: por región si KWin responde, si no recortadas de un cuadro entero."""

    def __init__(self, ruta=None):
        self._ruta = ruta        # archivo ya capturado: camino viejo de leer_hud(ruta=...)
        self._cuadro = None      # cuadro completo en gris, solo si hubo que caer atrás
        self._fallo = False      # ya se intentó y no hay captura posible

    def gris(self, caja):
        """Imagen en gris de esa caja, o None si no se puede capturar."""
        if self._cuadro is None and self._ruta is None and not self._fallo:
            im = captura_kwin.capturar(caja[0], caja[1],
                                       caja[2] - caja[0], caja[3] - caja[1])
            if im is not None:
                return im.convert("L")
        if self._cuadro is None and not self._fallo:
            try:
                self._cuadro = Image.open(self._ruta or _capturar()).convert("L")
            except Exception:                                   # noqa: BLE001
                self._fallo = True
        if self._fallo:
            return None
        return self._cuadro.crop(caja)

    def texto(self, caja, escala, whitelist, psm="7"):
        """OCR de la caja; si los píxeles no cambiaron desde la última vez, se reusa."""
        im = self.gris(caja)
        if im is None:
            return None
        pixeles = im.tobytes()
        previo = _LEIDOS.get(caja)
        if previo is not None and previo[0] == pixeles:
            return previo[1]
        texto = _ocr(im, (0, 0, im.width, im.height), escala, whitelist, psm)
        _LEIDOS[caja] = (pixeles, texto)
        return texto


def _oro_amplio(cajas):
    """El último número de 2+ dígitos del bloque inferior izquierdo es el oro.

    Robusto ante el desplazamiento del HUD: no depende de que el nivel tenga
    uno o dos dígitos, que es lo que corría la caja fija.
    """
    texto = cajas.texto(CAJA_ORO, 3, "0123456789, ", "6") or ""
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
    cajas = _Cajas(ruta)
    reloj = cajas.texto(CAJA_RELOJ, 6, "0123456789:")
    if reloj is None:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})", reloj)
    t = int(m.group(1)) * 60 + int(m.group(2)) if m else None
    return {"t": t, "oro": _oro_amplio(cajas), "ts": time.time()}


def _una_lectura_match(ruta=None):
    texto = _Cajas(ruta).texto(CAJA_MATCH, 8, "0123456789", "7")
    if not texto:
        return None
    m = re.search(r"(\d{6,})", texto.replace(" ", ""))
    return int(m.group(1)) if m else None


def leer_match_id(ruta=None):
    """Lee el 'MATCH: 123456789' de la esquina inferior derecha.

    Con una sola lectura, un dígito mal reconocido enganchaba una partida que no
    existía (visto: 134344094 en vez de 134294885). Se leen tres cuadros y gana el
    valor repetido; si los tres discrepan, se devuelve el primero y la capa de API
    decide si sirve.
    """
    if ruta:
        return _una_lectura_match(ruta)
    lecturas = []
    for i in range(3):
        valor = _una_lectura_match()
        if valor:
            lecturas.append(valor)
        if i < 2:
            time.sleep(0.15)
    if not lecturas:
        return None
    return max(set(lecturas), key=lecturas.count)


if __name__ == "__main__":
    for _ in range(3):
        print(leer_hud(), flush=True)
        time.sleep(1)

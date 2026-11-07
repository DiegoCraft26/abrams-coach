"""Detecta la ventana del juego dentro de la captura del escritorio.

El escritorio completo son los dos monitores. El juego ocupa uno, y puede estar
escalado (1080p en un panel 1440p) o con barras negras. Todo se normaliza a la caja
real del contenido para que las regiones sobrevivan a cambios de resolución o Alt-Tab.
"""
import re, subprocess
import numpy as np

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def geometria_monitores():
    """Devuelve [(nombre, x, y, ancho, alto)] leído de kscreen-doctor."""
    try:
        bruto = subprocess.run(["kscreen-doctor", "-o"], capture_output=True, text=True, timeout=10).stdout
        salida = ANSI.sub("", bruto)
    except Exception:
        return []
    monitores, actual = [], None
    for linea in salida.splitlines():
        limpio = linea.strip()
        if limpio.startswith("Output:"):
            partes = limpio.split()
            actual = {"nombre": partes[2] if len(partes) > 2 else "?", "habilitado": False}
            monitores.append(actual)
        elif actual and limpio.startswith("enabled"):
            actual["habilitado"] = True
        elif actual and limpio.startswith("Geometry:"):
            geo = limpio.split(":", 1)[1].strip()
            pos, tam = geo.split()
            x, y = (int(v) for v in pos.split(","))
            w, h = (int(v) for v in tam.split("x"))
            actual.update(x=x, y=y, ancho=w, alto=h)
    return [(m["nombre"], m["x"], m["y"], m["ancho"], m["alto"])
            for m in monitores if m.get("habilitado") and "x" in m]


def _caja_contenido(a, umbral=8.0):
    """Recorta las barras negras de una imagen (letterbox/pillarbox)."""
    brillo_f = a.mean(axis=(1, 2))
    brillo_c = a.mean(axis=(0, 2))
    filas = np.where(brillo_f > umbral)[0]
    cols = np.where(brillo_c > umbral)[0]
    if not len(filas) or not len(cols):
        return None
    return int(cols[0]), int(filas[0]), int(cols[-1])+1, int(filas[-1])+1


def detectar_ventana(ruta_escritorio, indice=None):
    """Devuelve (x0, y0, x1, y1) de la zona de juego dentro de la captura, o None."""
    from PIL import Image
    im = Image.open(ruta_escritorio).convert("RGB")
    a = np.asarray(im, dtype=np.float32)
    alto_total, ancho_total = a.shape[:2]

    monitores = [m for m in geometria_monitores() if m[1]+m[3] <= ancho_total and m[2]+m[4] <= alto_total]
    if not monitores:
        caja = _caja_contenido(a)
        return caja
    # el monitor del juego es el más grande
    monitores.sort(key=lambda m: m[3]*m[4], reverse=True)
    if indice is not None:
        monitores = [monitores[indice]]
    _, mx, my, mw, mh = monitores[0]
    sub = a[my:my+mh, mx:mx+mw]
    caja = _caja_contenido(sub)
    if not caja:
        return (mx, my, mx+mw, my+mh)
    x0, y0, x1, y1 = caja
    return (mx+x0, my+y0, mx+x1, my+y1)


def recortar_juego(ruta_escritorio, destino, indice=None):
    """Recorta la zona de juego. Devuelve (ruta, (x0,y0,x1,y1))."""
    from PIL import Image
    caja = detectar_ventana(ruta_escritorio, indice)
    im = Image.open(ruta_escritorio).convert("RGB")
    if not caja:
        im.save(destino)
        return destino, (0, 0, im.width, im.height)
    im.crop(caja).save(destino)
    return destino, caja

"""Refina la rejilla detectada buscando el desfase que maximiza el acierto de plantillas.

La detección por periodicidad da el paso y una posición aproximada; aquí se corrige el
origen probando desplazamientos y quedándose con el que reconoce más iconos.
"""
import numpy as np
from PIL import Image
from . import deteccion


def _celdas(x0, y0, paso, nx, ny, ancho, alto, lado=0.86):
    lista = []
    for f in range(ny):
        fila = []
        for c in range(nx):
            cx = x0 + paso/2 + c*paso
            cy = y0 + paso/2 + f*paso
            l = paso*lado
            fila.append([(cx-l/2)/ancho, (cy-l/2)/alto, l/ancho, l/alto])
        lista.append(fila)
    return lista


def _puntuar(im, celdas, ids, M, muestra=10):
    alto, ancho = im.size[1], im.size[0]
    planas = [(f, c) for f in range(len(celdas)) for c in range(len(celdas[f]))]
    if len(planas) > muestra:
        idx = np.linspace(0, len(planas)-1, muestra).astype(int)
        planas = [planas[i] for i in idx]
    total = 0.0
    for f, c in planas:
        x, y, w, h = celdas[f][c]
        caja = (int(x*ancho), int(y*alto), int((x+w)*ancho), int((y+h)*alto))
        if caja[2]-caja[0] < 6 or caja[3]-caja[1] < 6:
            continue
        celda = im.crop(caja)
        arr = np.asarray(celda, dtype=np.float32)/255.0
        if arr.std() < 0.02:
            continue
        mejor = 0.0
        for sub in deteccion._subcajas((0, 0, celda.size[0], celda.size[1])):
            punt = M @ deteccion._vec(celda.crop(sub))
            mejor = max(mejor, float(punt.max()))
        total += mejor
    return total/max(1, len(planas))


def refinar(ruta_imagen, auto, plantillas="items"):
    """Devuelve (x0, y0, paso, puntuación) refinados en píxeles de análisis."""
    ids, M = deteccion.matrices(plantillas)
    im = Image.open(ruta_imagen).convert("RGB")
    W, H = im.size
    ancho_a = auto["ancho_analisis"]
    alto_a = auto["alto_analisis"]
    escala_x = W/ancho_a
    escala_y = H/alto_a
    im_a = im.resize((ancho_a, alto_a))

    paso0 = auto["paso"][0]
    x0_0, y0_0 = auto["x0"], auto["y0"]
    nx, ny = auto["nx"], auto["ny"]

    mejor = (-1.0, x0_0, y0_0, paso0)
    for paso in (paso0-1, paso0, paso0+1):
        if paso < 8:
            continue
        for dx in range(-paso//2, paso//2 + 1, 3):
            for dy in range(-paso//2, paso//2 + 1, 3):
                celdas = _celdas(x0_0+dx, y0_0+dy, paso, nx, ny, ancho_a, alto_a)
                s = _puntuar(im_a, celdas, ids, M)
                if s > mejor[0]:
                    mejor = (s, x0_0+dx, y0_0+dy, paso)
    return mejor

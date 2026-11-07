"""Reconocimiento de iconos por plantilla, vectorizado con numpy."""
import os
import numpy as np
from PIL import Image

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONOS = os.path.join(DIR, "data", "iconos")
TAM = 48
_CACHE = {}


def _vec(im):
    a = np.asarray(im.convert("RGB").resize((TAM, TAM), Image.BILINEAR), dtype=np.float32) / 255.0
    v = a.reshape(-1)
    v = v - v.mean()
    n = np.linalg.norm(v)
    return v / n if n else v


def matrices(tipo="items"):
    """Devuelve (ids, matriz normalizada n x d)."""
    if tipo in _CACHE:
        return _CACHE[tipo]
    carpeta = os.path.join(ICONOS, tipo)
    ids, filas = [], []
    if os.path.isdir(carpeta):
        for arch in sorted(os.listdir(carpeta)):
            if not arch.endswith("_n.png"):
                continue
            try:
                filas.append(_vec(Image.open(os.path.join(carpeta, arch))))
                ids.append(arch[:-6])
            except Exception:
                continue
    M = np.vstack(filas) if filas else np.zeros((0, TAM*TAM*3), dtype=np.float32)
    _CACHE[tipo] = (ids, M)
    return _CACHE[tipo]


def _subcajas(caja):
    """Candidatos de recorte dentro de la celda: completo, 85% centrado, 70% centrado."""
    x0, y0, x1, y1 = caja
    w, h = x1-x0, y1-y0
    salida = [caja]
    for f in (0.85, 0.70):
        dx, dy = int(w*(1-f)/2), int(h*(1-f)/2)
        salida.append((x0+dx, y0+dy, x1-dx, y1-dy))
    return salida


def identificar(celda_im, tipo="items", top=3):
    ids, M = matrices(tipo)
    if not len(ids):
        return [(None, 0.0)]*top
    mejor_punt = None
    for caja in _subcajas((0, 0, celda_im.size[0], celda_im.size[1])):
        punt = M @ _vec(celda_im.crop(caja))
        if mejor_punt is None or punt.max() > mejor_punt.max():
            mejor_punt = punt
    idx = np.argsort(-mejor_punt)[:top]
    return [(ids[i], float(mejor_punt[i])) for i in idx]


def leer_celdas(img, celdas, umbral=0.55, tipo="items"):
    """Lee una lista de cajas exactas (fracciones) en vez de dividir una región."""
    im = Image.open(img).convert("RGB") if isinstance(img, str) else img.convert("RGB")
    W, H = im.size
    ids, M = matrices(tipo)
    salida = []
    for fila in celdas:
        f = []
        for (x, y, w, h) in fila:
            caja = (int(x*W), int(y*H), int((x+w)*W), int((y+h)*H))
            celda = im.crop(caja)
            arr = np.asarray(celda, dtype=np.float32)/255.0
            if arr.std() < 0.02:
                f.append({"id": None, "confianza": 0.0, "vacio": True})
                continue
            mejor_id, mejor_p = None, 0.0
            for sub in _subcajas((0, 0, celda.size[0], celda.size[1])):
                v = _vec(celda.crop(sub))
                punt = M @ v
                i = int(np.argmax(punt))
                if punt[i] > mejor_p:
                    mejor_id, mejor_p = ids[i], float(punt[i])
            f.append({"id": mejor_id if mejor_p >= umbral else None,
                      "confianza": round(mejor_p, 3)})
        salida.append(f)
    return salida


def leer_rejilla(img, region, nx, ny, umbral=0.60, tipo="items"):
    im = Image.open(img).convert("RGB") if isinstance(img, str) else img.convert("RGB")
    W, H = im.size
    x, y, w, h = region
    x0, y0 = int(x*W), int(y*H)
    x1, y1 = int((x+w)*W), int((y+h)*H)
    aw, ah = (x1-x0)/nx, (y1-y0)/ny
    ids, M = matrices(tipo)
    salida = []
    for fy in range(ny):
        fila = []
        for fx in range(nx):
            caja = (int(x0+fx*aw), int(y0+fy*ah), int(x0+(fx+1)*aw), int(y0+(fy+1)*ah))
            celda = im.crop(caja)
            arr = np.asarray(celda, dtype=np.float32)/255.0
            if arr.std() < 0.02:          # celda vacía o plana
                fila.append({"id": None, "confianza": 0.0, "vacio": True})
                continue
            mejor_id, mejor_p = None, 0.0
            for sub in _subcajas((0, 0, celda.size[0], celda.size[1])):
                v = _vec(celda.crop(sub))
                punt = M @ v
                i = int(np.argmax(punt))
                if punt[i] > mejor_p:
                    mejor_id, mejor_p = ids[i], float(punt[i])
            fila.append({"id": mejor_id if mejor_p >= umbral else None,
                         "confianza": round(mejor_p, 3)})
        salida.append(fila)
    return salida

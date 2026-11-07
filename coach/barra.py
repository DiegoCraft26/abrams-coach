"""Lee la barra superior del HUD: retratos, héroes y almas por jugador.

Se ancla en las bandas doradas que llevan el número de almas de cada jugador, así que
no depende de coordenadas fijas ni de la resolución.
"""
import subprocess
import numpy as np
from PIL import Image

DORADO = {"r_min": 150, "g_min": 90, "g_max": 200, "b_max": 90}


def _bandas_doradas(a, alto_max):
    """Devuelve cajas de las bandas doradas de la fila superior."""
    franja = a[:alto_max]
    r, g, b = franja[:, :, 0], franja[:, :, 1], franja[:, :, 2]
    mask = ((r > DORADO["r_min"]) & (g > DORADO["g_min"]) & (g < DORADO["g_max"])
            & (b < DORADO["b_max"]) & (r > g + 30))
    if not mask.any():
        return []
    # etiquetado por tramos
    alto, ancho = mask.shape
    etiquetas = np.zeros((alto, ancho), dtype=np.int32)
    actual = 0
    previos = []
    for y in range(alto):
        fila = mask[y]
        if not fila.any():
            previos = []
            continue
        cambios = np.flatnonzero(np.diff(np.r_[False, fila, False].astype(np.int8)))
        tramos = list(zip(cambios[0::2], cambios[1::2]))
        actuales = []
        for ini, fin in tramos:
            tocados = [e for (pi, pf, e) in previos if pf > ini and pi < fin]
            if tocados:
                et = tocados[0]
                for e in tocados[1:]:
                    etiquetas[etiquetas == e] = et
            else:
                actual += 1
                et = actual
            actuales.append((ini, fin, et))
            etiquetas[y, ini:fin] = et
        previos = actuales

    cajas = []
    for et in np.unique(etiquetas):
        if et == 0:
            continue
        ys, xs = np.where(etiquetas == et)
        if len(ys) < 200:
            continue
        ancho_c = xs.max()-xs.min()+1
        alto_c = ys.max()-ys.min()+1
        if not (20 <= ancho_c <= 160 and 10 <= alto_c <= 60):
            continue
        cajas.append({"x0": int(xs.min()), "y0": int(ys.min()),
                      "x1": int(xs.max())+1, "y1": int(ys.max())+1})
    cajas.sort(key=lambda c: c["x0"])
    return cajas


def _ocr_numero(im, caja, escala=6):
    c = im.crop((caja["x0"], caja["y0"], caja["x1"], caja["y1"]))
    if c.width < 8 or c.height < 6:
        return None
    c = c.resize((c.width*escala, c.height*escala), Image.LANCZOS)
    arr = np.asarray(c.convert("L"), dtype=np.float32)
    # texto claro sobre fondo dorado: quedarse con lo más brillante
    umbral = arr.mean() + arr.std()*1.1
    b = (arr > umbral).astype(np.uint8)*255
    ruta = "/tmp/num.png"
    Image.fromarray(b).save(ruta)
    r = subprocess.run(["tesseract", ruta, "stdout", "--psm", "7",
                        "-c", "tessedit_char_whitelist=0123456789"],
                       capture_output=True, text=True)
    texto = r.stdout.strip()
    return int(texto) if texto.isdigit() and 1 <= len(texto) <= 5 else None


def leer(ruta_juego, alto_max=170):
    """Devuelve {"bandas": [...], "almas": [...], "ancho": W, "alto": H}."""
    im = Image.open(ruta_juego).convert("RGB")
    a = np.asarray(im)
    bandas = _bandas_doradas(a.astype(np.int16), alto_max)
    almas = []
    for c in bandas:
        almas.append(_ocr_numero(im, c))
    return {
        "ancho": im.width, "alto": im.height,
        "bandas": bandas,
        "almas": almas,
        "legibles": sum(1 for v in almas if v is not None),
        "total": len(bandas),
    }

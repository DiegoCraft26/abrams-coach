"""Construye el banco de plantillas de dígitos a partir de capturas con verdad terreno.

Uso:
    python3 herramientas/construir_plantillas.py

Lee las capturas y valores declarados en VERDAD, recorta los glifos reales del juego y
los guarda en coach/plantillas_digitos.npz. No usa tesseract: las etiquetas vienen del
valor conocido, así que el banco no puede quedar mal etiquetado.

Los trozos donde dos glifos se tocan (pasa con "11" y "14") se parten buscando
exhaustivamente los cortes que minimizan el costo contra las etiquetas conocidas.
"""
import itertools
import json
import os
import sys

import numpy as np
from PIL import Image

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import plantillas as P  # noqa: E402

# Capturas con valor conocido. Se leen las almas de las 12 columnas y el reloj.
VERDAD = [
    {
        "archivo": "salida/calibracion/marcador_real_juego.png",
        "almas": [3152, 878, 923, 1120, 914, 1422, 1025, 1025, 714, 3098, 3098, 3098],
        "reloj": "7:40",
    },
]

BANDA_MIN, BANDA_MAX = 200, 700      # franja vertical donde buscar la fila de almas
ANCHOS = (20, 45)                    # ancho plausible de un número de almas


def luminancia(im):
    return np.asarray(im.convert("RGB")).astype(np.int16).max(axis=2)


def clusters(mask, gap=18, wmin=ANCHOS[0], wmax=ANCHOS[1]):
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return []
    salida, s, p = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - p > gap:
            if wmin <= p - s + 1 <= wmax:
                salida.append((int(s), int(p)))
            s = i
        p = i
    if wmin <= p - s + 1 <= wmax:
        salida.append((int(s), int(p)))
    return salida


def banda_almas(lum):
    """Localiza la fila de almas: exactamente 12 grupos de ancho variable."""
    mejor = None
    alto = lum.shape[0]
    for y in range(BANDA_MIN, min(BANDA_MAX, alto)):
        cl = clusters(lum[max(0, y - 2):y + 3, :].max(axis=0) > 185)
        if len(cl) == 12:
            w = [e - s + 1 for s, e in cl]
            variedad = max(w) - min(w)
            if mejor is None or variedad > mejor[0]:
                mejor = (variedad, y, cl)
    if mejor is None:
        return None
    _, y0, cajas = mejor
    x0, x1 = cajas[0][0], cajas[-1][1]
    sub = lum[:, x0:x1 + 1] > 185
    filas = np.flatnonzero(sub.sum(axis=1) > 20)
    filas = filas[np.abs(filas - y0) <= 10]
    return int(filas.min()), int(filas.max()), cajas


def binarizar(crop):
    """Máscara float 0..1 de tinta sobre fondo oscuro."""
    c = crop.astype(np.float32)
    lo, hi = float(c.min()), float(c.max())
    if hi - lo < 25:
        return np.zeros_like(c, dtype=np.float32)
    thr = lo + (hi - lo) * 0.55
    return ((c > thr).astype(np.float32))


def partir_conocido(mask, etiquetas, banco, ancho_min=3, ancho_max=13):
    """Parte un trozo pegajoso sabiendo qué dígitos contiene.

    Devuelve la lista de máscaras recortadas, una por etiqueta, o None si no hay
    ninguna partición posible con anchos razonables.
    """
    ancho = mask.shape[1]
    n = len(etiquetas)
    if n == 0:
        return None
    if n == 1:
        return [mask]
    # todas las formas de repartir `ancho` en n trozos contiguos no vacíos
    mejor = (None, float("inf"))
    cortes_posibles = range(ancho_min, ancho_max + 1)
    for cortes in itertools.product(cortes_posibles, repeat=n - 1):
        anchos = list(cortes) + [ancho - sum(cortes)]
        if anchos[-1] < ancho_min or anchos[-1] > ancho_max:
            continue
        xs, acc = [], 0
        for w in anchos:
            xs.append((acc, acc + w))
            acc += w
        piezas = [P.normalizar(mask[:, a:b]) for a, b in xs]
        costo = sum(banco.costo(p, e) for p, e in zip(piezas, etiquetas))
        if costo < mejor[1]:
            mejor = (xs, costo)
    if mejor[0] is None:
        return None
    return [mask[:, a:b] for a, b in mejor[0]]


def cosechar(banco, ruta, almas, reloj=None, verbose=True):
    """Cosecha los glifos de una captura usando el MISMO recorte y umbral que la lectura.

    Esto es la regla clave del banco: si la cosecha y la lectura no preprocesan igual,
    las plantillas no sirven. Por eso se importan `recorte_columna` y `_tinta` del
    módulo de producción en vez de reimplementarlos.
    """
    from coach import marcador as M

    im = M._rgb(ruta)
    lum = M._lum(im)
    banda = M.banda_almas(lum)
    if banda is None:
        print(f"  {os.path.basename(ruta)}: no encontré la banda de almas")
        return 0
    y0, y1, cajas = banda
    if verbose:
        print(f"  banda y={y0}..{y1}, {len(cajas)} columnas")

    ratio = M.RATIO_PLANTILLAS
    pendientes = []
    agregados = 0
    for col, caja in enumerate(cajas):
        esperado = str(almas[col])
        crop = M.recorte_columna(lum, y0, y1, caja)
        mask = M._tinta(crop, ratio)
        trozos = P.trozos(mask)
        if len(trozos) == len(esperado):
            for (a, b), d in zip(trozos, esperado):
                banco.agregar(d, mask[:, a:b + 1])
                agregados += 1
            if verbose:
                print(f"    col{col:2d} {esperado:>5s} directo  ({len(trozos)} glifos)")
        else:
            pendientes.append((col, esperado, mask, trozos))

    # 2ª pasada: trozos pegados, ya con las plantillas de la 1ª
    for col, esperado, mask, trozos in pendientes:
        partes = partir_conocido(mask, esperado, banco)
        if partes is None:
            print(f"    col{col:2d} {esperado:>5s} NO se pudo resolver "
                  f"({len(trozos)} trozos para {len(esperado)} dígitos)")
            continue
        for pieza, d in zip(partes, esperado):
            banco.agregar(d, pieza)
            agregados += 1
        if verbose:
            print(f"    col{col:2d} {esperado:>5s} resuelto por búsqueda de cortes")

    if reloj:
        n = cosechar_reloj(banco, im, reloj)
        agregados += n
        if verbose:
            print(f"    reloj {reloj} -> {n} glifos")
    return agregados


def composiciones(n, k):
    """Todas las formas de repartir n dígitos en k trozos, cada trozo con ≥1."""
    if k == 1:
        if n >= 1:
            yield (n,)
        return
    for primero in range(1, n - k + 2):
        for resto in composiciones(n - primero, k - 1):
            yield (primero,) + resto


def region_reloj(im):
    """Caja del reloj en fracciones del área de juego (medida sobre captura real)."""
    return (0.4688, 0.0028, 0.0859, 0.0292)


def cosechar_reloj(banco, im, texto):
    W, H = im.size
    x, y, w, h = region_reloj(im)
    caja = (int(x * W), int(y * H), int((x + w) * W), int((y + h) * H))
    lum = luminancia(im.crop(caja))
    # umbral adaptativo: el texto es lo más claro de la caja (llega a ~200, no más)
    lo, hi = int(lum.min()), int(lum.max())
    thr = lo + (hi - lo) * 0.58
    mask = (lum > thr).astype(np.float32)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return 0
    mask = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    trozos = P.trozos(mask, ancho_min=2)
    print(f"      reloj: umbral={thr:.0f} trozos={[(b-a+1) for a,b in trozos]}")
    piezas = [mask[:, a:b + 1] for a, b in trozos]
    k = len(piezas)
    if len(piezas) == 0:
        return 0
    # asignar las etiquetas conocidas a los trozos (mismo número o resolución)
    if len(piezas) == len(texto):
        for sub, ch in zip(piezas, texto):
            banco.agregar(ch, sub)
        return len(piezas)
    # si no cuadra, resolver por composiciones con el banco actual
    n, kk = len(texto), len(piezas)
    mejor = (None, float("inf"))
    for comp in composiciones(n, kk):
        pasada, costo, ok, pos = [], 0.0, True, 0
        for idx, cuantos in enumerate(comp):
            etiquetas = texto[pos:pos + cuantos]
            pos += cuantos
            sub = piezas[idx]
            if cuantos == 1:
                pasada.append([sub])
                costo += banco.costo(P.normalizar(sub), etiquetas)
            else:
                partes = partir_conocido(sub, etiquetas, banco)
                if partes is None:
                    ok = False
                    break
                pasada.append(partes)
                costo += sum(banco.costo(P.normalizar(p), e)
                             for p, e in zip(partes, etiquetas))
        if ok and costo < mejor[1]:
            mejor = (pasada, costo)
    if mejor[0] is None:
        return 0
    pos, total = 0, 0
    for grupo in mejor[0]:
        for pieza in grupo:
            banco.agregar(texto[pos], pieza)
            pos += 1
            total += 1
    return total


def main():
    banco = P.Banco()
    total = 0
    for caso in VERDAD:
        ruta = os.path.join(RAIZ, caso["archivo"])
        print(f"cosechando {caso['archivo']}")
        total += cosechar(banco, ruta, caso["almas"], caso.get("reloj"))
    destino = banco.guardar(meta={"origen": "capturas reales con verdad terreno",
                                 "fecha": "2026-11-07"})
    print(f"\n{total} glifos -> {destino}")
    print("por clase:", banco.resumen())


if __name__ == "__main__":
    main()

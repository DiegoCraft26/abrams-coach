"""Calibración automática por periodicidad.

No busca colores ni iconos concretos: mide dónde hay bordes y detecta el ritmo de la
cuadrícula. Así funciona igual con iconos claros, oscuros o desaturados.
"""
import numpy as np

PASO_MIN = 18     # px entre centros de iconos (a 1280 de ancho)
PASO_MAX = 140
FUERZA_MIN = 0.32  # cuánta energía explica el ritmo; por debajo no hay cuadrícula


def _perfil(grad, eje):
    p = grad.sum(axis=eje).astype(np.float64)
    if p.size < 8:
        return p
    # quitar tendencia suave
    k = max(5, len(p)//40)
    suave = np.convolve(p, np.ones(k)/k, mode="same")
    return p - suave


def _ritmo(perfil, paso_min=PASO_MIN, paso_max=PASO_MAX):
    """Paso y fase por autocorrelación. Devuelve (paso, fase, fuerza)."""
    n = len(perfil)
    if n < paso_min*3:
        return None
    p = np.asarray(perfil, dtype=np.float64)
    p = p - p.mean()
    if not np.any(p):
        return None
    # autocorrelación por FFT
    tam = 1 << int(np.ceil(np.log2(2*n)))
    f = np.fft.rfft(p, tam)
    ac = np.fft.irfft(f*np.conj(f), tam)[:n]
    if ac[0] <= 0:
        return None
    ac = ac/ac[0]

    maximo = 0.0
    for lag in range(paso_min, min(paso_max, n//2)):
        if ac[lag] > ac[lag-1] and ac[lag] >= ac[lag+1]:
            maximo = max(maximo, ac[lag])
    if maximo <= 0.10:
        return None

    # primer pico que explique al menos el 70% del mejor: evita elegir un múltiplo
    paso = None
    for lag in range(paso_min, min(paso_max, n//2)):
        if ac[lag] > ac[lag-1] and ac[lag] >= ac[lag+1] and ac[lag] >= maximo*0.70:
            paso = lag
            break
    if paso is None:
        return None

    # fase: desfase que maximiza la suma en las posiciones del paso
    mejor_fase, mejor_val = 0, -1e18
    for fase in range(paso):
        idx = np.arange(fase, n, paso)
        v = float(p[idx].sum())
        if v > mejor_val:
            mejor_val, mejor_fase = v, fase

    fuerza = float(min(1.0, max(0.0, (maximo - 0.10)/0.55)))
    return paso, mejor_fase, round(fuerza, 3)


def detectar_rejilla(ruta_imagen, ancho_analisis=1280):
    """Devuelve {"region":[x,y,w,h], "nx", "ny", ...} o None."""
    from PIL import Image
    im = Image.open(ruta_imagen).convert("L")
    W0, H0 = im.size
    ancho = min(ancho_analisis, W0)
    alto = max(1, int(H0*ancho/W0))
    a = np.asarray(im.resize((ancho, alto)), dtype=np.float32)

    gx = np.abs(np.diff(a, axis=1))[:-1, :]      # (alto-1, ancho-1)
    gy = np.abs(np.diff(a, axis=0))[:, :-1]      # (alto-1, ancho-1)
    grad = np.zeros((alto-1, ancho-1), dtype=np.float32)
    grad += gx + gy

    px = _perfil(grad, 0)
    py = _perfil(grad, 1)
    rx = _ritmo(px)
    ry = _ritmo(py)
    if not rx or not ry:
        return None
    paso_x, fase_x, fx = rx
    paso_y, fase_y, fy = ry
    fuerza = min(fx, fy)
    if fuerza < FUERZA_MIN:
        return None

    # zona con ritmo: columnas y filas donde el perfil periódico manda
    def zona(perfil, paso, fase):
        idx = np.arange(fase, len(perfil), paso)
        umbral = perfil[idx].mean()*0.45
        vivos = [i for i in idx if perfil[i] >= umbral]
        if not vivos:
            return None
        return min(vivos), max(vivos)

    zx = zona(px, paso_x, fase_x)
    zy = zona(py, paso_y, fase_y)
    if not zx or not zy:
        return None
    x0, x1 = zx
    y0, y1 = zy

    # extender media celda para cubrir los iconos completos
    x0 = max(0, x0 - paso_x//2); x1 = min(ancho-1, x1 + paso_x//2)
    y0 = max(0, y0 - paso_y//2); y1 = min(alto-1, y1 + paso_y//2)

    # los iconos son cuadrados y la rejilla es regular: un solo paso para ambos ejes
    paso = int(round((paso_x + paso_y)/2))
    if paso < PASO_MIN:
        return None

    def celdas_con(desfase):
        lista = []
        for f in range(ny_est):
            fila = []
            for c in range(nx_est):
                cx = x0 + desfase + paso/2 + c*paso
                cy = y0 + desfase + paso/2 + f*paso
                lado = paso*0.86
                fila.append([(cx-lado/2)/ancho, (cy-lado/2)/alto, lado/ancho, lado/alto])
            lista.append(fila)
        return lista

    nx_est = max(1, round((x1-x0)/paso))
    ny_est = max(1, round((y1-y0)/paso))

    return {
        "region": [x0/ancho, y0/alto, (x1-x0)/ancho, (y1-y0)/alto],
        "nx": int(nx_est), "ny": int(ny_est),
        "paso": [paso, paso],
        "fuerza": fuerza,
        "x0": x0, "y0": y0, "ancho_analisis": ancho, "alto_analisis": alto,
        "candidatas": [celdas_con(0), celdas_con(paso//2)],
    }

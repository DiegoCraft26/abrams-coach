"""Banco de plantillas de dígitos extraídas del PROPIO juego y emparejador.

Por qué existe: tesseract falla con la tipografía de Deadlock a 11 px de alto, que es
el tamaño real de las almas del marcador. En vez de pelear con el OCR genérico, se
recortan los glifos de capturas reales cuyo valor se conoce (verdad terreno) y se
comparan por distancia normalizada.

Todo el módulo trabaja sobre máscaras binarias de float en [0,1]:
  0 = fondo, 1 = tinta.
"""
import os
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
RUTA_BANCO = os.path.join(AQUI, "plantillas_digitos.npz")

# Tamaño al que se normaliza cada glifo antes de comparar.
FORMA = (16, 24)          # (alto, ancho)

_cache_indices = {}


def _indices(alto, ancho):
    """Tablas de interpolación bilineal para pasar de (alto, ancho) a FORMA.

    Se cachean por forma: los glifos del marcador tienen 3 o 4 formas distintas, así
    que la tabla se calcula una vez por captura y no por glifo. Sin esto, normalizar
    costaba ~1 ms por candidato y la lectura se iba a 700 ms.
    """
    clave = (alto, ancho)
    tablas = _cache_indices.get(clave)
    if tablas is not None:
        return tablas
    h, w = FORMA
    yy = (np.arange(h, dtype=np.float64) + 0.5) * (alto / h) - 0.5
    xx = (np.arange(w, dtype=np.float64) + 0.5) * (ancho / w) - 0.5
    y0 = np.clip(np.floor(yy), 0, alto - 1).astype(np.intp)
    x0 = np.clip(np.floor(xx), 0, ancho - 1).astype(np.intp)
    y1 = np.clip(y0 + 1, 0, alto - 1)
    x1 = np.clip(x0 + 1, 0, ancho - 1)
    wy = np.clip(yy - np.floor(yy), 0.0, 1.0).astype(np.float64)[:, None]
    wx = np.clip(xx - np.floor(xx), 0.0, 1.0).astype(np.float64)[None, :]
    tablas = (y0, y1, x0, x1, wy, wx)
    if len(_cache_indices) > 400:
        _cache_indices.clear()
    _cache_indices[clave] = tablas
    return tablas


def normalizar(mask):
    """Lleva una máscara de cualquier tamaño a FORMA, con interpolación bilineal."""
    m = np.asarray(mask, dtype=np.float32)
    if m.size == 0:
        return np.zeros(FORMA, dtype=np.float32)
    if m.shape == FORMA:
        return m
    y0, y1, x0, x1, wy, wx = _indices(*m.shape)
    arr = m.astype(np.float64)
    arriba = arr[y0][:, x0] * (1 - wx) + arr[y0][:, x1] * wx
    abajo = arr[y1][:, x0] * (1 - wx) + arr[y1][:, x1] * wx
    return (arriba * (1 - wy) + abajo * wy).astype(np.float32)


def distancia(a, b):
    """Distancia media normalizada entre dos glifos ya normalizados."""
    return float(np.abs(a - b).mean())


class Banco:
    """Conjunto de ejemplos por clase. Una clase es un carácter: '0'..'9' o ':'."""

    def __init__(self, ejemplos=None):
        self.ejemplos = ejemplos or {}      # clase -> lista de máscaras normalizadas

    def clases(self):
        return sorted(self.ejemplos)

    def agregar(self, clase, mask):
        self.ejemplos.setdefault(clase, []).append(normalizar(mask))

    def costo(self, mask_norm, clase):
        """Costo de que `mask_norm` sea `clase`: mínimo contra todos sus ejemplos."""
        ej = self.ejemplos.get(clase)
        if not ej:
            return 1.0
        return min(distancia(mask_norm, e) for e in ej)

    def mejor(self, mask_norm, clases=None):
        """Devuelve (clase, costo) de la mejor coincidencia."""
        clases = clases or self.clases()
        mejor, costo = None, 9.9
        for c in clases:
            d = self.costo(mask_norm, c)
            if d < costo:
                mejor, costo = c, d
        return mejor, costo

    # ---------------------------------------------------------------- persistencia
    def guardar(self, ruta=RUTA_BANCO, meta=None):
        import json
        arreglos = {}
        manifiesto = {"forma": list(FORMA), "clases": {}}
        for clase, lista in self.ejemplos.items():
            manifiesto["clases"][clase] = len(lista)
            for i, m in enumerate(lista):
                arreglos[f"c{clase!r}_{i}"] = m.astype(np.float32)
        if meta:
            manifiesto["meta"] = meta
        arreglos["__manifiesto__"] = np.frombuffer(
            json.dumps(manifiesto).encode("utf-8"), dtype=np.uint8)
        np.savez_compressed(ruta, **arreglos)
        return ruta

    @classmethod
    def cargar(cls, ruta=RUTA_BANCO):
        import json
        if not os.path.exists(ruta):
            return None
        datos = np.load(ruta, allow_pickle=False)
        manifiesto = json.loads(bytes(datos["__manifiesto__"]).decode("utf-8"))
        banco = cls()
        for clase, n in manifiesto["clases"].items():
            for i in range(n):
                banco.ejemplos[clase] = banco.ejemplos.get(clase, [])
                banco.ejemplos[clase].append(datos[f"c{clase!r}_{i}"].astype(np.float32))
        return banco

    def resumen(self):
        return {c: len(v) for c, v in sorted(self.ejemplos.items())}


def trozos(mask, ancho_min=2):
    """Parte una máscara en trozos por columnas vacías.

    Devuelve [(x0, x1)] inclusivos. Los trozos más angostos que `ancho_min` se
    descartan como ruido.
    """
    if mask.size == 0:
        return []
    prof = (mask > 0.5).sum(axis=0)
    salida, ini = [], None
    for x, v in enumerate(prof):
        if v > 0:
            if ini is None:
                ini = x
        elif ini is not None:
            salida.append((ini, x - 1))
            ini = None
    if ini is not None:
        salida.append((ini, len(prof) - 1))
    return [(a, b) for a, b in salida if b - a + 1 >= ancho_min]


def leer_trozo(mask, banco, ancho_min=3, ancho_max=13, penal=0.06):
    """Lee los dígitos de un trozo que puede tener glifos pegados.

    En vez de cortar por anchura fija (que confunde "11" con "4"), busca la mejor
    segmentación posible con programación dinámica: cada candidato cuesta su
    distancia al mejor dígito más una pequeña penalización por carácter.

    Devuelve (texto, costo_medio). Costo bajo = se parece a un glifo real del juego.
    """
    if mask.size == 0:
        return "", 9.9
    alto, ancho = mask.shape
    if ancho < ancho_min:
        return "", 9.9

    cache = {}
    INF = float("inf")
    dp = np.full(ancho + 1, INF, dtype=np.float64)
    prev = [None] * (ancho + 1)
    dp[0] = 0.0
    for j in range(1, ancho + 1):
        for i in range(max(0, j - ancho_max), j - ancho_min + 1):
            if dp[i] == INF:
                continue
            fila = cache.setdefault(i, {})
            if j not in fila:
                m = normalizar(mask[:, i:j])
                fila[j] = banco.mejor(m)
            clase, costo = fila[j]
            total = dp[i] + costo + (penal if j - i <= 5 else 0.0)
            if total < dp[j]:
                dp[j] = total
                prev[j] = (i, clase, costo)
    if dp[ancho] == INF:
        return "", 9.9

    cadena, costos = [], []
    j = ancho
    while j > 0 and prev[j] is not None:
        i, clase, costo = prev[j]
        cadena.append(clase)
        costos.append(costo)
        j = i
    cadena.reverse()
    costos.reverse()
    if not cadena:
        return "", 9.9
    return "".join(cadena), float(sum(costos) / len(costos))

"""Utilidades comunes del módulo macro: caché en disco, pacing y estadística.

Reglas que impone:
- Nada de red sin pasar por `Presupuesto`, que impone ≤150 peticiones por ventana
  móvil de 60 s (la API anuncia 200 req/min; se deja margen) y un intervalo mínimo.
- Un 429 se respeta: se lee `Retry-After`, se espera y no se insiste más de 3 veces.
- Toda escritura es atómica (tmp + rename) para que un corte no deje JSON a medias.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import time

BASE = "https://api.deadlock-api.com"
CABECERAS = {
    "User-Agent": "abrams-coach/macro (Linux; estudio de progresion de rango)",
    "Accept": "application/json",
}

MAX_POR_MINUTO = 150          # anunciado 200; margen de seguridad
INTERVALO_MIN_S = 0.45        # ~133/min sostenido
MAX_REINTENTOS_429 = 3


class Freno(Exception):
    """La API pidió parar (429 persistente). Se detiene la corrida, no se insiste."""


class Presupuesto:
    """Ventana móvil de peticiones. Persistente para no reiniciar el conteo al reanudar."""

    def __init__(self, ruta_estado, max_por_minuto=MAX_POR_MINUTO,
                 intervalo_min=INTERVALO_MIN_S):
        self.ruta = ruta_estado
        self.max_por_minuto = max_por_minuto
        self.intervalo_min = intervalo_min
        self.marcas = []
        self.total = 0
        self._cargar()

    def _cargar(self):
        try:
            with open(self.ruta, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        ahora = time.time()
        self.marcas = [t for t in d.get("marcas", []) if ahora - t < 120]
        self.total = int(d.get("total", 0))

    def _guardar(self):
        _escribir_json(self.ruta, {"marcas": self.marcas[-200:], "total": self.total})

    def esperar(self):
        ahora = time.time()
        self.marcas = [t for t in self.marcas if ahora - t < 60]
        if len(self.marcas) >= self.max_por_minuto:
            pausa = 60 - (ahora - self.marcas[0]) + 0.5
            if pausa > 0:
                time.sleep(pausa)
                ahora = time.time()
                self.marcas = [t for t in self.marcas if ahora - t < 60]
        if self.marcas:
            pausa = self.intervalo_min - (ahora - self.marcas[-1])
            if pausa > 0:
                time.sleep(pausa)
        self.marcas.append(time.time())
        self.total += 1
        self._guardar()


def _escribir_json(ruta, dato):
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(ruta)), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dato, f, ensure_ascii=False)
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


escribir_json = _escribir_json


def leer_json(ruta, defecto=None):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def traer(presupuesto, url, timeout=180):
    """GET con JSON de vuelta. Reintenta 5xx; se frena con 429 (ver módulo)."""
    import urllib.error
    import urllib.request

    ultimo = None
    for intento in range(4):
        presupuesto.esperar()
        try:
            req = urllib.request.Request(url, headers=CABECERAS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            cuerpo = ""
            try:
                cuerpo = e.read()[:200].decode("utf-8", "replace")
            except Exception:                                     # noqa: BLE001
                pass
            if e.code == 429:
                espera = _retry_after(e) if intento < MAX_REINTENTOS_429 else None
                if espera is None:
                    raise Freno(f"429 persistente en {url}: {cuerpo}") from e
                print(f"    429 · espero {espera:.0f}s (intento {intento + 1})", flush=True)
                time.sleep(espera)
                ultimo = e
                continue
            if e.code in (400, 403, 404):
                raise RuntimeError(f"HTTP {e.code} en {url}: {cuerpo}") from e
            ultimo = e
            time.sleep(3 * (intento + 1))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            ultimo = e
            time.sleep(3 * (intento + 1))
    raise RuntimeError(f"sin respuesta de {url}: {ultimo}")


def _retry_after(e):
    for cabecera in ("Retry-After", "X-RateLimit-Reset"):
        valor = e.headers.get(cabecera) if getattr(e, "headers", None) else None
        if valor:
            try:
                return max(1.0, float(valor))
            except ValueError:
                pass
    return 30.0


# ---------------------------------------------------------------- estadística
def mann_whitney(x, y):
    """U de Mann-Whitney bilateral (aprox. normal con corrección de empates).

    Devuelve dict con n1, n2, U, z, p, delta de Cliff. Sin dependencias externas.
    """
    x = [float(v) for v in x if v is not None]
    y = [float(v) for v in y if v is not None]
    n1, n2 = len(x), len(y)
    if n1 < 3 or n2 < 3:
        return {"n1": n1, "n2": n2, "U": None, "z": None, "p": None, "delta": None}
    todos = sorted(x + y)
    rangos = {}
    i = 0
    while i < len(todos):
        j = i
        while j + 1 < len(todos) and todos[j + 1] == todos[i]:
            j += 1
        rango = (i + j) / 2.0 + 1.0
        rangos[todos[i]] = rango
        i = j + 1
    r1 = sum(rangos[v] for v in x)
    u1 = r1 - n1 * (n1 + 1) / 2.0
    u2 = n1 * n2 - u1
    u = min(u1, u2)
    media = n1 * n2 / 2.0
    # corrección por empates
    n = n1 + n2
    from collections import Counter
    cuentas = Counter(todos)
    empates = sum(c ** 3 - c for c in cuentas.values() if c > 1)
    var = n1 * n2 / 12.0 * ((n + 1) - empates / (n * (n - 1))) if n > 1 else 0.0
    if var <= 0:
        return {"n1": n1, "n2": n2, "U": u, "z": None, "p": None, "delta": None}
    z = (abs(u1 - media) - 0.5) / math.sqrt(var)
    p = 2.0 * (1.0 - _phi(abs(z)))
    delta = 2.0 * u1 / (n1 * n2) - 1.0
    return {"n1": n1, "n2": n2, "U": u, "z": round(z, 3), "p": p,
            "delta": round(delta, 3)}


def _phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def fisher_exact(a, b, c, d):
    """Fisher bilateral para tabla 2x2 (a,b / c,d). Conteos enteros."""
    n = a + b + c + d
    if min(a, b, c, d) < 0 or n == 0:
        return None
    fila1 = a + b
    fila2 = c + d
    col1 = a + c

    def prob(k):
        return (math.comb(fila1, k) * math.comb(fila2, col1 - k)) / math.comb(n, col1)

    lim_inf = max(0, col1 - fila2)
    lim_sup = min(fila1, col1)
    observada = prob(a)
    p = sum(prob(k) for k in range(lim_inf, lim_sup + 1) if prob(k) <= observada * 1.000000001)
    return min(1.0, p)


def mediana(valores):
    v = sorted(float(x) for x in valores if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2.0

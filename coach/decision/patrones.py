"""Patrones de Deadlock que el motor usa para razonar (no para inventar datos).

Todo lo que hay aquí está medido o documentado con fecha y fuente; si algo no se pudo
verificar, se dice explícitamente. Los números de economía se usan para traducir
"te faltan 1,240 almas" a algo accionable ("4 oleadas"), no para fingir precisión.

Fuentes (consultadas el 2026-11-07):
  - Benchmark de almas de Abrams: Blitz.gg (build del 31-oct-2026): ~7.6k almas a los
    10 min y ~25.5k a los 25 min. https://blitz.gg/tr/deadlock/heroes/abrams/builds
  - Fases por coste total: deadlocked.gg (parche 30-oct-2026): Early 8,000 · Mid 13,600 ·
    Late 22,400. https://deadlocked.gg/heroes/abrams/
  - Economía: trooper 100 + 2/min; Guardian 1,375; Walker 3,675; Mid-Boss 1,500 + 25/min
    (reducido a la mitad el 30-oct-2026); Soul Urn 250 + 70/min.
    https://steamdb.com/es-ES/deadlock/patches/minor-update-09-16-2026-2026-09-16-steam-community-announcements-1844115010490072
    https://gamerheadlines.com/deadlock-halloween-2026-gameplay-update/
    https://deadlock-boosting.com/blog/deadlock-spawn-times
"""

from . import heroe as _heroe

# Hitos y fases salen de `data/heroes/<clave>.json`. Se mantienen los nombres HITOS y
# FASES por compatibilidad con lo que ya los importaba.
HITOS = _heroe.cargar("abrams").hitos
FASES = _heroe.cargar("abrams").fases

# Economía por evento (almas). Se usan para traducir déficits a objetivos.
ECONOMIA = {
    "trooper_base": 100.0,
    "trooper_por_min": 2.0,
    "guardian": 1375,
    "walker": 3675,
    "midboss_base": 1500.0,
    "midboss_por_min": 25.0,
    "urn_base": 250.0,
    "urn_por_min": 70.0,
    "oleada_troopers": 4,
}


def benchmark_almas(t_s, heroe=None):
    """Almas que un build de Abrams debería tener en el segundo t (interpolado).

    Es una referencia de comunidad (Blitz.gg), no una verdad del juego: se usa para decir
    "vas por debajo del build", nunca para decidir por sí sola.
    """
    hitos = heroe.hitos if heroe is not None else HITOS
    t = max(0.0, float(t_s or 0))
    if t <= hitos[0][0]:
        return hitos[0][1] * t / hitos[0][0]
    for (t0, a0), (t1, a1) in zip(hitos, hitos[1:]):
        if t <= t1:
            return a0 + (a1 - a0) * (t - t0) / (t1 - t0)
    return hitos[-1][1]


def desvio(t_s, almas, heroe=None):
    """Cuánto se aparta el jugador del benchmark: positivo = por delante."""
    if almas is None:
        return None
    return float(almas) - benchmark_almas(t_s, heroe)


def fase_economica(almas, heroe=None):
    """EARLY / MID / LATE / CIERRE según el coste acumulado del build."""
    if almas is None:
        return "DESCONOCIDA"
    fases = heroe.fases if heroe is not None else FASES
    valor = float(almas)
    for nombre, tope in fases:
        if valor < tope:
            return nombre
    return "CIERRE"


def hito_siguiente(almas, heroe=None):
    """Almas del siguiente hito de build que aún no se alcanza (o None si ya está todo)."""
    if almas is None:
        return None
    for _, tope in (heroe.fases if heroe is not None else FASES):
        if float(almas) < tope:
            return tope
    return None


def trooper_valor(t_s):
    """Almas que vale un trooper en el minuto dado (100 + 2/min)."""
    return ECONOMIA["trooper_base"] + ECONOMIA["trooper_por_min"] * (max(0.0, t_s) / 60.0)


def oleadas_para(almas_faltantes, t_s):
    """Traduce un déficit de almas a oleadas de troopers (lo que puedes farmear)."""
    if not almas_faltantes or almas_faltantes <= 0:
        return 0
    por_oleada = trooper_valor(t_s) * ECONOMIA["oleada_troopers"]
    if por_oleada <= 0:
        return 0
    return int(round(almas_faltantes / por_oleada))


def objetivo_farm(almas_faltantes, t_s):
    """Texto accionable para el estado FARM: almas y oleadas equivalentes."""
    oleadas = oleadas_para(almas_faltantes, t_s)
    if not almas_faltantes or almas_faltantes <= 0:
        return "ya vas parejo: sigue el ritmo"
    if oleadas <= 0:
        return f"recupera {int(almas_faltantes):,} almas"
    return (f"recupera {int(almas_faltantes):,} almas ≈ {oleadas} oleadas "
            f"({objetivo_evento(almas_faltantes, t_s)})")


def objetivo_evento(almas_faltantes, t_s):
    """Qué objetivo del mapa cubre el déficit, con los valores actuales del parche."""
    precio_guardian = ECONOMIA["guardian"]
    precio_walker = ECONOMIA["walker"]
    if almas_faltantes >= precio_walker:
        return "un Walker te lo paga entero"
    if almas_faltantes >= precio_guardian:
        return "un Guardián te lo paga"
    return "un par de kills y las oleadas"

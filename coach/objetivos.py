"""Objetivos del mapa en el plan: walkers y ritmo de almas.

Caso real que lo motivó (2026-11-15): el equipo nunca tumbó un walker y la economía se
quedó corta, pero el panel seguía pidiendo el siguiente ítem como si el ritmo fuera
normal. Walkers y objetivos no se ven en el broadcast (no hay estado de mapa), así que
aquí no se adivinan: se compara el **ritmo de almas** propio con el del equipo enemigo
—ambos leídos por HTTP— y el déficit se traduce a walkers con el valor medido del juego
(`patrones.ECONOMIA`, 3 675 almas por walker). Si el ritmo no está por debajo, no se dice
nada: un aviso que siempre suena deja de leerse.
"""
from __future__ import annotations

# 8 % por debajo del rival ya es «vas corto»: por debajo de eso es ruido de early game.
UMBRAL_DELTA = -0.08
# Antes del minuto 8 no se habla de objetivos: en la calle se pelea por olas, no por walkers.
T_MIN_OBJETIVO = 480
# El ritmo necesita algo de partida para significar algo.
T_MIN_RITMO = 180


def _ritmo(almas, t_s):
    if almas is None or not t_s:
        return None
    return float(almas) / (float(t_s) / 60.0)


def evaluar(estado):
    """Ritmo propio vs enemigo y déficit traducido a walkers. Nota corta o nada."""
    vacio = {"ritmo": None, "ritmo_enemigo": None, "delta_pct": None,
             "deficit": None, "walkers": None, "prioridad": False,
             "nota": "", "motivo": ""}
    t = float(getattr(estado, "t", 0) or 0)
    if t < T_MIN_RITMO:
        return vacio
    yo = (estado.yo.almas if estado.yo else None)
    ritmo = _ritmo(yo, t)
    if ritmo is None:
        return vacio
    salida = dict(vacio, ritmo=round(ritmo, 1))

    almas_enemigas = [j.almas for j in (estado.enemigos or []) if j.almas is not None]
    if not almas_enemigas:
        return salida
    ritmo_enemigo = _ritmo(sum(almas_enemigas) / len(almas_enemigas), t)
    if not ritmo_enemigo:
        return salida
    salida["ritmo_enemigo"] = round(ritmo_enemigo, 1)
    delta = (ritmo - ritmo_enemigo) / ritmo_enemigo
    salida["delta_pct"] = round(delta, 3)
    # Déficit en almas (lo que te separa del ritmo enemigo a estas alturas).
    deficit = max(0.0, (ritmo_enemigo - ritmo) * (t / 60.0))
    salida["deficit"] = int(round(deficit))

    if t < T_MIN_OBJETIVO or delta > UMBRAL_DELTA:
        return salida

    salida["prioridad"] = True
    salida["motivo"] = "vas corto de almas: te faltan objetivos"
    walker = 3675  # patrones.ECONOMIA["walker"]; se importa abajo sin coste si no hay datos
    try:
        from .decision import patrones
        walker = int(patrones.ECONOMIA.get("walker") or walker)
    except Exception:                                       # noqa: BLE001
        pass
    cuantos = deficit / walker if walker else 0
    salida["walkers"] = round(cuantos, 1)
    if cuantos >= 0.2:
        salida["nota"] = (
            f"vas {deficit:,.0f} almas por debajo del rival (~{cuantos:.1f} walker"
            f"{'s' if cuantos >= 1.5 else ''}, {walker:,} c/u). Ese hueco no se recupera "
            f"comprando: farmea la ola y empuja objetivo antes de pelear.")
    else:
        salida["nota"] = (
            f"vas {deficit:,.0f} almas por debajo del rival: farmea antes de pelear, "
            f"no gastes en un 800 suelto.")
    return salida

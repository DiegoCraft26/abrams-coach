"""Objetivos del mapa: el ritmo de almas decide si el plan pide farmear o comprar.

Caso real que lo motivó (2026-11-15): el equipo nunca tumbó un walker y la economía se
quedó corta, pero el panel seguía pidiendo el siguiente ítem como si el ritmo fuera
normal. Aquí se fija la regla: solo se avisa si el ritmo va corto **y** la partida ya
tiene objetivos (≥ 8 min). Sin datos, silencio.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coach.estado import Estado  # noqa: E402
from coach.motor_api import Motor  # noqa: E402
from coach.objetivos import UMBRAL_DELTA, evaluar  # noqa: E402

M = Motor()


def _estado(mias, enemigas, t):
    return Estado.desde_dict({
        "t": t, "yo": {"heroe": "Abrams", "almas": mias},
        "enemigos": [{"heroe": "haze", "almas": enemigas},
                     {"heroe": "seven", "almas": enemigas},
                     {"heroe": "lash", "almas": enemigas}],
    })


def test_ritmo_corto_marca_prioridad():
    e = evaluar(_estado(4000, 8000, 1200))
    assert e["prioridad"] is True
    assert e["delta_pct"] is not None and e["delta_pct"] < 0
    assert "walker" in e["nota"].lower()


def test_ritmo_parejo_no_dice_nada():
    e = evaluar(_estado(8000, 8000, 1200))
    assert e["prioridad"] is False
    assert e["nota"] == ""


def test_antes_del_minuto_8_no_se_habla_de_objetivos():
    # Aunque vaya corto, en early game se pelea por olas, no por walkers.
    e = evaluar(_estado(500, 2000, 300))
    assert e["prioridad"] is False


def test_sin_datos_suficientes_calla():
    e = evaluar(Estado.desde_dict({"t": 0}))
    assert e["prioridad"] is False
    assert e["ritmo"] is None


def test_el_motor_publica_objetivos_y_avisa_en_el_motivo():
    r = M.analizar_dict({
        "t": 1200, "yo": {"heroe": "Abrams", "almas": 3000, "items": []},
        "aliados": [{"almas": 3000}],
        "enemigos": [{"heroe": h, "almas": 9000} for h in ("haze", "seven", "lash")],
        "confianza": 1.0,
    })
    obj = r.get("objetivos")
    assert obj is not None, "el motor no publica objetivos"
    assert obj["prioridad"] is True
    assert obj["delta_pct"] <= UMBRAL_DELTA
    # Y el plan lo tiene en cuenta: el ahorro fino pasa a farmeo.
    if r["decision"]["accion"] == "AHORRAR":
        assert "objetivos" in (r["decision"].get("motivo") or "").lower() or \
            r["decision"].get("modo") in ("farm",)

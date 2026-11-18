"""Ventas específicas y su presencia en el plan (feedback de Diego, 2026-11-15).

Regla que fija esta suite: el panel nunca dice «VENDER» sin decir **qué** se vende y
**qué** entra, y cuando hay venta el primer paso del camino la lleva anotada.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coach.motor_api import Motor  # noqa: E402

M = Motor()
ITEMS = M.conoc["items"]
ARMAS = sorted([i for i, d in ITEMS.items() if d.get("slot") == "weapon"],
               key=lambda i: ITEMS[i].get("costo") or 0)


def _estado(almas, t, heroes=("haze", "seven", "lash")):
    return {"t": t, "yo": {"heroe": "Abrams", "almas": almas, "items": ARMAS[:4]},
            "aliados": [{"almas": almas}],
            "enemigos": [{"heroe": h, "almas": almas} for h in heroes],
            "confianza": 1.0}


def _casos():
    return [(almas, t) for almas in (3000, 8000, 20000) for t in (900, 1800)]


def test_ninguna_orden_de_vender_sin_nombres():
    """Si la acción es VENDER, hay que poder nombrar qué sale y qué entra."""
    for almas, t in _casos():
        r = M.analizar_dict(_estado(almas, t))
        dec = r["decision"]
        if dec.get("accion") != "VENDER":
            continue
        v = r.get("venta")
        assert v, f"VENDER sin detalle en almas={almas} t={t}"
        assert v["nombre"], "la venta no dice el nombre del ítem que sale"
        assert str(v["vender"]) in {str(i) for i in ARMAS[:4]}
        assert v["comprar"] == str(dec["item"]["id"]), (
            "la venta no es para el ítem que toca comprar")
        assert "vende" in dec["motivo"].lower()


def test_venta_siempre_de_algo_que_llevas():
    """Nunca se propone vender un ítem que no está en el inventario."""
    poseidos = {str(i) for i in ARMAS[:4]}
    for almas, t in _casos():
        r = M.analizar_dict(_estado(almas, t))
        v = r.get("venta")
        if v:
            assert str(v["vender"]) in poseidos, f"vende {v['vender']} y no lo tiene"


def test_hay_casos_que_proponen_venta():
    """La función se usa: con slot lleno y minuto avanzado, alguna propuesta sale.

    Si esto falla, la venta volvió a ser código muerto (era el caso antes del arreglo).
    """
    propuestas = [M.analizar_dict(_estado(a, t))["venta"] for a, t in _casos()]
    assert any(propuestas), "ningún caso propone vender: la venta está apagada"


def test_el_plan_lleva_la_venta_en_el_primer_paso():
    """«Tomarlas en cuenta en el plan»: el paso que toca se pinta con su venta."""
    for almas, t in _casos():
        r = M.analizar_dict(_estado(almas, t))
        v = r.get("venta")
        if not v or not r.get("camino"):
            continue
        primero = r["camino"][0]
        assert primero.get("vende") == v["nombre"], (
            f"el paso de ahora ({primero.get('nombre')}) no menciona la venta "
            f"de {v['nombre']}")
        assert str(primero.get("vende_id")) == str(v["vender"])


def test_sin_slot_lleno_no_hay_venta():
    """Con hueco libre no se vende nada: no se toca el inventario de gratis."""
    est = _estado(8000, 1800)
    est["yo"]["items"] = ARMAS[:2]
    r = M.analizar_dict(est)
    assert r.get("venta") is None, r.get("venta")
    assert r["decision"].get("accion") != "VENDER"

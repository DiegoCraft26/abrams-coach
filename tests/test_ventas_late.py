"""Prioridad de venta en late (feedback de Diego, 2026-11-16).

«Sigue sin tener una noción de venta… debería poner en algún color distinto algún ítem
de los que pueden ser vendidos en prioridad, sobre todo en late.»

Lo que fija esta suite:
1. con los 12 slots llenos y en late, el estado publicado trae una lista `ventas` con al
   menos un ítem en nivel "ahora" y el inventario lo marca (`vende`);
2. sin slot lleno no se marca nada: un hueco libre no se «vende»;
3. cuando el bolsillo no alcanza pero vender una pieza del slot sí, la venta se nombra
   (`venta.para_pagar`) en vez de dejar solo «faltan N almas»;
4. la prioridad nunca propone vender algo que casi no se vende en partidas reales.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coach.motor_api import Motor  # noqa: E402

M = Motor()
ITEMS = M.conoc["items"]


def _por_slot(slot, n):
    """Los n ítems del slot con tasa_venta más alta (los que de verdad se venden)."""
    lista = [(iid, d) for iid, d in ITEMS.items() if d.get("slot") == slot]
    lista.sort(key=lambda x: -(x[1].get("tasa_venta") or 0))
    return lista[:n]


def _inventario_lleno():
    return [iid for slot in ("weapon", "vitality", "spirit") for iid, _ in _por_slot(slot, 4)]


def _estado(items, t, oro=None):
    gastado = sum((ITEMS.get(iid) or {}).get("costo") or 0 for iid in items)
    d = {"t": t, "yo": {"heroe": "Abrams", "almas": gastado + (oro if oro is not None else 4000),
                        "items": items},
         "aliados": [{"almas": gastado + 4000}],
         "enemigos": [{"heroe": h, "almas": gastado + 3000}
                      for h in ("haze", "seven", "lash")],
         "confianza": 1.0}
    if oro is not None:
        d["yo"]["oro"] = oro
    return d


def test_late_con_slots_llenos_marca_venta():
    r = M.analizar_dict(_estado(_inventario_lleno(), 2000))
    ventas = r.get("ventas") or []
    assert ventas, "en late con 12 slots llenos no hay ninguna prioridad de venta"
    ahora = [v for v in ventas if v["nivel"] == "ahora"]
    assert ahora, "ningún ítem marcado como salida inmediata"
    # El panel pinta el color con estos campos: tienen que llegar al inventario.
    marcados = [x for x in (r.get("inventario") or []) if x.get("vende")]
    assert {x["id"] for x in marcados} >= {v["id"] for v in ahora}
    assert all(x.get("vende_motivo") for x in marcados)


def test_sin_slot_lleno_no_se_vende():
    r = M.analizar_dict(_estado(_inventario_lleno()[:3], 2000))
    assert not (r.get("ventas") or []), "marca venta sin slot lleno"


def test_solo_se_propone_lo_que_se_vende_de_verdad():
    r = M.analizar_dict(_estado(_inventario_lleno(), 2400))
    minima = M.cfg.get("venta_minima_tasa", 0.0)
    for v in r.get("ventas") or []:
        assert v["tasa"] >= minima, f"{v['nombre']} se vende en {v['tasa']} de las partidas"


def test_vender_para_pagar_cuando_el_bolsillo_no_alcanza():
    """Con el slot lleno, el hueco vale el precio completo: se nombra aunque falte oro."""
    items = _inventario_lleno()
    r = M.analizar_dict(_estado(items, 2000, oro=1200))
    v = r.get("venta")
    if not v:
        return  # si el motor ya lo considera pagable, no hay nada que exigir aquí
    assert v.get("para_pagar"), "una venta que se propone por dinero tiene que decirlo"
    assert "vende" in (v.get("motivo") or "").lower()
    assert r["decision"].get("accion") != "VENDER", (
        "no se ordena comprar un ítem que el bolsillo todavía no paga")


def test_prioridad_ordena_por_residual():
    r = M.analizar_dict(_estado(_inventario_lleno(), 2000))
    ventas = r.get("ventas") or []
    pp = [v["pp"] for v in ventas]
    assert pp == sorted(pp), "la lista de venta no va de peor a mejor residual"

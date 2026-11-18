"""El recorte de `/api/estado` a la tarjeta: sin GTK y con pruebas.

Se separó de `overlay.py` justamente para poder probarlo. Aquí se fija lo que la tarjeta
enseña y, sobre todo, lo que NO: sin «faltan», sin «te alcanza» y sin inventar un nombre
cuando el estado no lo trae.
"""
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas"))

import overlay_datos as D  # noqa: E402


def test_recorta_el_item_y_el_camino():
    estado = {"listo": True, "decision": {
        "accion": "COMPRAR",
        "item": {"id": "1", "nombre": "Weighted Shots", "costo": 3200, "faltan": 800},
        "camino": [{"id": "1", "estado": "ahora"}, {"id": "2", "estado": "despues"}]}}
    r = D.resumen(estado)
    assert r["nombre"] == "Weighted Shots"
    assert r["costo"] == 3200
    assert [t["clase"] for t in r["tiles"]] == ["ahora", "despues"]
    assert "faltan" not in r and "alcanza" not in r


def test_sin_decision_usa_el_primer_ahora_del_camino():
    estado = {"camino": [{"id": "9", "nombre": "Otro", "estado": "ahora", "costo": 800}]}
    r = D.resumen(estado)
    assert r["nombre"] == "Otro"
    assert r["costo"] == 800


def test_sin_partida_y_con_objetivo_lo_enseña():
    r = D.resumen({"listo": False, "objetivo": {"texto": "3 de 5 con ≤6 muertes"}})
    assert r["objetivo"] == "3 de 5 con ≤6 muertes"
    assert r["nombre"] == ""


def test_vende_solo_si_la_accion_es_vender():
    d = {"decision": {"accion": "AHORRAR", "item": {"nombre": "X", "costo": 1}},
         "venta": {"nombre": "Close Quarters"}}
    assert D.resumen(d)["vende"] == ""
    d["decision"]["accion"] = "VENDER"
    assert D.resumen(d)["vende"] == "Close Quarters"


def test_tiles_y_miles():
    assert D._miles(3200) == "3,200"
    assert D._num("12.7") == 13
    assert D._num(None) == 0

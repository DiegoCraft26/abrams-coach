"""Camino por héroe: los tramos salen de partidas reales y las habilidades no cuentan.

El error que fija esta prueba (2026-11-15): el array `items` del metadata mezcla compras
de tienda con subidas de habilidad. Sin filtrar, la «apertura» de Abrams salía Shoulder
Charge, Infernal Resilience y Seismic Impact, que son sus habilidades.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import camino_heroe as C            # noqa: E402
from coach.fuentes import items_assets as IA  # noqa: E402

CATALOGO = {"465043967": {"nombre": "Spirit Strike", "costo": 800},
            "2829638276": {"nombre": "Extra Regen", "costo": 800},
            "800008313": {"nombre": "Crushing Fists", "costo": 6400},
            "2824119765": {"nombre": "Shoulder Charge", "costo": None}}
TIPOS = {"465043967": {"nombre": "Spirit Strike", "tipo": "upgrade", "costo": 800},
         "2829638276": {"nombre": "Extra Regen", "tipo": "upgrade", "costo": 800},
         "800008313": {"nombre": "Crushing Fists", "tipo": "upgrade", "costo": 6400},
         "2824119765": {"nombre": "Shoulder Charge", "tipo": "ability", "costo": None}}


def partida(gano, compras):
    return {"gano": gano, "items": [[iid, t, 0] for iid, t in compras]}


def test_las_habilidades_no_cuentan_como_compra(monkeypatch):
    monkeypatch.setattr(IA, "_cache", {"datos": TIPOS, "ts": 1e12})
    p = [partida(True, [(2824119765, 90), (465043967, 100)]) for _ in range(60)]
    d = C.derivar(p, catalogo=CATALOGO, min_n=10)
    nombres = [f["nombre"] for f in d["tramos"]["0-10"]]
    assert "Spirit Strike" in nombres
    assert "Shoulder Charge" not in nombres


def test_los_tramos_son_por_minuto_de_compra(monkeypatch):
    monkeypatch.setattr(IA, "_cache", {"datos": TIPOS, "ts": 1e12})
    p = [partida(True, [(465043967, 100), (2829638276, 700),
                        (800008313, 1300)]) for _ in range(60)]
    d = C.derivar(p, catalogo=CATALOGO, min_n=10)
    assert [f["nombre"] for f in d["tramos"]["0-10"]] == ["Spirit Strike"]
    assert [f["nombre"] for f in d["tramos"]["10-20"]] == ["Extra Regen"]
    assert [f["nombre"] for f in d["tramos"]["20-30"]] == ["Crushing Fists"]


def test_solo_ganadoras_filtra(monkeypatch):
    monkeypatch.setattr(IA, "_cache", {"datos": TIPOS, "ts": 1e12})
    p = ([partida(True, [(465043967, 100)]) for _ in range(30)]
         + [partida(False, [(2829638276, 100)]) for _ in range(30)])
    todas = C.derivar(p, catalogo=CATALOGO, min_n=10)
    solo = C.derivar(p, catalogo=CATALOGO, min_n=10, solo_ganadoras=True)
    assert todas["n_partidas"] == 60 and solo["n_partidas"] == 30
    assert [f["nombre"] for f in solo["tramos"]["0-10"]] == ["Spirit Strike"]


def test_sin_partidas_devuelve_estructura_vacia():
    d = C.derivar([], catalogo=CATALOGO)
    assert d == {"n_partidas": 0, "apertura": [], "tramos": {}, "primera_compra": []}


def test_la_primera_compra_es_la_mas_temprana(monkeypatch):
    monkeypatch.setattr(IA, "_cache", {"datos": TIPOS, "ts": 1e12})
    p = [partida(True, [(2829638276, 40), (465043967, 12)]) for _ in range(60)]
    d = C.derivar(p, catalogo=CATALOGO, min_n=10)
    assert d["primera_compra"][0]["nombre"] == "Spirit Strike"


def test_guardar_y_cargar(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ruta_heroe", lambda h: str(tmp_path / f"{h}-camino.json"))
    d = C.derivar([partida(True, [(465043967, 100)])] * 60, catalogo=CATALOGO, min_n=10)
    C.guardar(13, d, extra={"fuente": "prueba"})
    vuelto = C.cargar(13)
    assert vuelto["heroe"] == 13 and vuelto["fuente"] == "prueba"


def test_plan_para_usa_el_tramo_del_minuto():
    camino = {"tramos": {
        "0-10": [{"id": "111", "nombre": "Apertura", "costo": 800, "n": 500}],
        "10-20": [{"id": "222", "nombre": "Medio", "costo": 3000, "n": 400}],
        "20-30": [{"id": "333", "nombre": "Tarde", "costo": 6400, "n": 300}]}}
    assert [p["nombre"] for p in C.plan_para(13, 300, camino=camino)] == ["Apertura"]
    assert [p["nombre"] for p in C.plan_para(13, 900, camino=camino)] == ["Medio"]
    assert [p["nombre"] for p in C.plan_para(13, 1500, camino=camino)] == ["Tarde"]


def test_plan_para_sin_camino_devuelve_none(monkeypatch):
    monkeypatch.setattr(C, "cargar", lambda h: None)
    assert C.plan_para(99, 600) is None


def test_plan_para_trae_icono_y_muestra():
    camino = {"tramos": {"0-10": [{"id": "465043967", "nombre": "Spirit Strike",
                                   "costo": 800, "n": 900}]}}
    plan = C.plan_para(6, 60, camino=camino)
    assert plan[0]["icono"] == "/icono/465043967"
    assert plan[0]["n"] == 900


def test_aplicar_a_salida_con_otro_heroe_cambia_el_plan(monkeypatch):
    camino = {"tramos": {"10-20": [{"id": "222", "nombre": "Medio", "costo": 3000,
                                    "n": 400}]}}
    original = C.plan_para
    monkeypatch.setattr(C, "plan_para", lambda hid, t: original(hid, t, camino=camino))
    monkeypatch.setattr("coach.historico.nombre_a_id", lambda: {"haze": 13})
    salida = {"t": 900, "plan": [{"id": "1", "nombre": "De Abrams"}],
              "recomendaciones": [{"id": "x"}], "estado": {"estado": "EQUILIBRIO"}}
    assert C.aplicar_a_salida(salida, "haze") is True
    assert [p["nombre"] for p in salida["plan"]] == ["Medio"]
    assert salida["recomendaciones"] == []
    assert "camino observado de haze" in salida["estado"]["motivo"]


def test_con_abrams_no_toca_nada():
    salida = {"t": 900, "plan": [{"id": "1"}], "recomendaciones": [{"id": "x"}]}
    assert C.aplicar_a_salida(salida, "abrams") is False
    assert len(salida["plan"]) == 1 and salida["recomendaciones"]


def test_sin_camino_del_heroe_no_toca_nada(monkeypatch):
    monkeypatch.setattr(C, "plan_para", lambda hid, t: None)
    monkeypatch.setattr("coach.historico.nombre_a_id", lambda: {"kelvin": 12})
    salida = {"t": 900, "plan": [{"id": "1"}], "recomendaciones": [{"id": "x"}]}
    assert C.aplicar_a_salida(salida, "kelvin") is False
    assert len(salida["plan"]) == 1

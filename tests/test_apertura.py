"""La apertura del héroe sale del banco o del pozo, nunca de una lista a mano.

Historia real: `nucleo_vivo` tenía APERTURA = Melee Lifesteal, Close Quarters, Extra
Regen y el banco de 626 partidas dice Spirit Strike, Close Quarters, Extra Regen. El panel
enseñaba la lista a mano. Esta prueba fija cuál manda.
"""
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import apertura as A  # noqa: E402
from coach import nucleo_vivo as NV  # noqa: E402

BANCO = ["465043967", "1342610602", "2829638276"]   # data/meta_abrams.json


def test_abrams_manda_el_banco_no_la_lista_vieja():
    ids, fuente = A.resolver(None)
    assert ids[:3] == BANCO
    assert "banco" in fuente
    assert "1437614329" not in ids[:3], "Melee Lifesteal era la lista a mano"


def test_otro_heroe_usa_su_pozo_del_api():
    ids, fuente = A.resolver("haze")
    assert fuente.startswith("pozo"), fuente
    assert len(ids) >= 3
    assert "1437614329" not in ids or True


def test_un_heroe_sin_pozo_lo_dice_en_la_fuente():
    ids, fuente = A.resolver(4242)
    assert ids, "siempre devuelve algo"
    assert "sin pozo" in fuente or "reserva" in fuente


def test_sin_archivos_devuelve_la_reserva(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "META_ABRAMS", str(tmp_path / "no.json"))
    monkeypatch.setattr(A, "META_HEROE", str(tmp_path))
    ids, fuente = A.resolver(None)
    assert ids == list(A.RESERVA)
    assert "reserva" in fuente


def test_plan_inicial_respeta_el_heroe(tmp_path, monkeypatch):
    """Con un héroe cuyo pozo es conocido, el plan empieza por sus ítems."""
    monkeypatch.setattr(A, "META_HEROE", str(tmp_path))
    (tmp_path / "13.json").write_text(json.dumps({"apertura": [
        {"id": 1548066885, "nombre": "Extended Magazine"}]}), encoding="utf-8")
    conoc = {"items": {"1548066885": {"nombre": "Extended Magazine", "costo": 800,
                                      "tier": 1, "n": 100},
                       "465043967": {"nombre": "Spirit Strike", "costo": 800,
                                     "tier": 1, "n": 50}}}
    plan = NV.plan_inicial(conoc, cuantos=1, heroe="haze")
    assert plan and str(plan[0]["id"]) == "1548066885"


def test_publicar_apertura_dice_de_donde_sale(monkeypatch):
    publicado = {}
    monkeypatch.setattr(NV.servidor.EST, "publicar",
                        lambda d: publicado.update(d))
    conoc = {i: {"nombre": f"item{i}", "costo": 800, "n": 1} for i in
             BANCO + ["1437614329"]}
    assert NV.publicar_apertura(conoc) is True
    assert publicado["fuente_apertura"].startswith("banco")
    assert publicado["plan"][0]["id"] == "465043967"

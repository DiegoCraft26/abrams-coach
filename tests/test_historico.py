"""Histórico de composiciones: el aviso que ve Diego tiene que salir del archivo real.

Lo que se prueba: que los pares se cuenten una vez por partida, que la consulta traduzca
nombres del broadcast a ids, que no afirme nada sin muestra y que el índice guardado se
pueda releer sin reconstruir 47 000 partidas en cada arranque.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import historico as H  # noqa: E402


def partida(mid, aliados, enemigos, gano):
    jugadores = [{"slot": 0, "team": 0, "hero": 6}]
    jugadores += [{"slot": i + 1, "team": 0, "hero": h} for i, h in enumerate(aliados)]
    jugadores += [{"slot": 6 + i, "team": 1, "hero": h} for i, h in enumerate(enemigos)]
    return {"match_id": mid, "start_time": "2026-11-01 10:00:00", "gane": gano,
            "yo": {"slot": 0, "team": 0}, "jugadores": jugadores}


def normalizadas(crudo):
    from coach.variantes import cargar_preparado
    return cargar_preparado(crudo)


def test_cuenta_pares_una_vez_por_partida_aunque_se_repitan_heroes():
    p = normalizadas([partida(1, [7, 8, 9, 10, 11], [12, 13, 14, 15, 16, 17], True)])
    ind = H.construir(p)
    assert ind["total"] == 1 and ind["victorias"] == 1
    assert ind["pares"]["12,13"] == [1, 1]
    assert len(ind["pares"]) == 15, "6 enemigos dan 15 pares"
    assert ind["comp"]["12,13,14,15,16,17"] == [1, 1]


def test_consulta_traduce_nombres_del_broadcast():
    crudo = [partida(i, [7, 8, 9, 10, 11], [12, 13, 14, 15, 16, 17], i % 2 == 0)
             for i in range(1, 41)]
    ind = H.construir(normalizadas(crudo))
    # Kelvin=12, Haze=13 según data/heroes.json
    r = H.consultar(ind, ["Kelvin", "Haze"], min_n=10)
    assert r["pares"], r
    assert r["pares"][0]["n"] >= 10


def test_sin_muestra_no_afirma_nada():
    crudo = [partida(1, [7, 8, 9, 10, 11], [12, 13, 14, 15, 16, 17], True)]
    ind = H.construir(normalizadas(crudo))
    r = H.consultar(ind, [12, 13], min_n=100)
    assert r["pares"] == [] and r["aviso"] == ""


def test_el_aviso_nombra_a_los_heroes_no_a_los_ids():
    crudo = [partida(i, [7, 8, 9, 10, 11], [12, 13, 14, 15, 16, 17], i % 3 != 0)
             for i in range(1, 201)]
    ind = H.construir(normalizadas(crudo))
    r = H.consultar(ind, [12, 13, 14, 15, 16, 17], min_n=100)
    assert "Kelvin" in r["aviso"] or "Haze" in r["aviso"], r["aviso"]
    assert "+" in r["aviso"]


def test_la_plantilla_completa_se_informa_si_existe():
    crudo = [partida(i, [7, 8, 9, 10, 11], [12, 13, 14, 15, 16, 17], i % 2 == 0)
             for i in range(1, 21)]
    ind = H.construir(normalizadas(crudo))
    r = H.consultar(ind, [12, 13, 14, 15, 16, 17], min_n=5)
    assert r["comp"] and r["comp"]["n"] == 20
    assert "20 veces" in r["aviso"] or "20 vez" in r["aviso"]


def test_guardar_y_releer_no_reconstruye(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "ARCHIVO", str(tmp_path / "historico.json.gz"))
    ind = H.construir(normalizadas([partida(1, [7, 8, 9, 10, 11],
                                            [12, 13, 14, 15, 16, 17], True)]))
    H.guardar(ind)
    H._CACHE.update({"indice": None, "ts": 0.0})
    vuelto = H.indice(0)
    assert vuelto["total"] == 1
    assert vuelto["pares"]["12,13"] == [1, 1]


def test_para_panel_nunca_lanza_sin_indice(monkeypatch):
    monkeypatch.setattr(H, "indice", lambda *a, **k: {"total": 0, "comp": {}, "pares": {}})
    assert H.para_panel(["Haze", "Kelvin"]) == {}
    assert H.para_panel(None) == {}


def test_los_nombres_del_api_tapan_los_ids_sin_nombre():
    """El 2026-11-15 el panel mostraba «86» y «88»: eran Violet y Baba."""
    from coach.fuentes import heroes_nombres as HN

    local = {"6": {"id": 6, "nombre": "Abrams"}, "86": {"id": 86}}
    api = [{"id": 86, "name": "Violet"}, {"id": 6, "name": "Abrams"},
           {"id": 88, "name": "Baba"}]
    nuevo = HN.combinar(local, api)
    assert nuevo["86"]["nombre"] == "Violet"
    assert nuevo["88"]["nombre"] == "Baba"
    assert nuevo["6"]["nombre"] == "Abrams"
    assert "nombre_anterior" not in nuevo["6"], "no cambió, no se anota"


def test_combinar_no_borra_heroes_retirados():
    from coach.fuentes import heroes_nombres as HN

    nuevo = HN.combinar({"99": {"id": 99, "nombre": "Retirado"}}, [])
    assert nuevo["99"]["nombre"] == "Retirado"

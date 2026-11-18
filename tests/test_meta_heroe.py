"""Meta por héroe: la regla de apertura y su control contra el banco de Abrams.

El caso que justifica todo esto: ordenar por winrate o por popularidad NO reproduce lo
que compran los que ganan (Melee Lifesteal y Restorative Shot salen arriba sin estar en
la apertura real). Lo que discrimina es cuándo se compra. Con el agregado real de Abrams
—guardado en `tests/datos/item-stats-abrams.json`— la regla tiene que recuperar los tres
ítems de `data/meta_abrams.json`, que vienen de 626 partidas jugadas.
"""
import json
import os

from coach import meta_heroe as M

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOGO = os.path.join(RAIZ, "data", "catalogo.json")
AGREGADO_REAL = os.path.join(RAIZ, "tests", "datos", "item-stats-abrams.json")


def _fila(item_id, wins=50000, losses=48000, rel=12.0):
    return {"item_id": item_id, "wins": wins, "losses": losses,
            "players": wins // 3, "matches": wins + losses,
            "avg_buy_time_relative": rel, "bucket": 0}


CATALOGO_FALSO = {
    "1": {"id": 1, "nombre": "Barato y temprano", "costo": 800},
    "2": {"id": 2, "nombre": "Barato pero tarde", "costo": 800},
    "3": {"id": 3, "nombre": "Caro y temprano", "costo": 3000},
    "4": {"id": 4, "nombre": "Barato con poca muestra", "costo": 800},
    "5": {"id": 5, "nombre": "Barato y temprano mejor", "costo": 800},
}


def test_solo_entra_lo_barato_temprano_y_con_muestra():
    filas = [
        _fila(1, 50000, 48000, rel=10.0),
        _fila(2, 50000, 48000, rel=60.0),        # tarde
        _fila(3, 50000, 48000, rel=5.0),         # caro
        _fila(4, 10, 5, rel=5.0),                # ruido
        _fila(5, 60000, 40000, rel=20.0),        # el mejor winrate
    ]
    d = M.derivar(filas, catalogo=CATALOGO_FALSO)
    ids = [c["id"] for c in d["apertura"]]
    assert ids[0] == 5, "ordena por cota inferior de winrate"
    assert 1 in ids
    assert 2 not in ids, "comprado tarde no es apertura"
    assert 3 not in ids, "3000 de oro no es salida"
    assert 4 not in ids, "15 partidas no son muestra"


def test_la_base_y_la_muestra_se_calculan_del_agregado():
    filas = [_fila(1, 600, 400), _fila(5, 400, 600)]
    d = M.derivar(filas, catalogo=CATALOGO_FALSO, min_muestra=1)
    assert d["base_wr"] == 0.5
    assert d["muestra"] == 2000


def test_wilson_no_premia_rachas_cortas():
    assert M.wilson(3, 0) < M.wilson(300, 0)
    assert M.wilson(0, 0) == 0.0


def test_con_el_agregado_real_de_abrams_recupera_la_apertura_del_banco():
    with open(AGREGADO_REAL, encoding="utf-8") as f:
        filas = json.load(f)
    with open(os.path.join(RAIZ, "data", "meta_abrams.json"), encoding="utf-8") as f:
        meta = json.load(f)
    esperados = [int(x["id"]) for x in meta["apertura_detalle"][:3]]

    d = M.derivar(filas)
    r = M.comparar(d, esperados)
    assert r["faltan"] == [], f"el pozo dejó fuera {r['faltan']}"
    assert r["aciertos"] == 3
    # Y no mete cualquier cosa: como mucho cinco candidatos.
    assert len(d["apertura"]) <= 5


def test_la_regla_esta_en_los_limites_que_se_imprimieron():
    assert M.REL_MAX == 27.0
    assert M.COSTO_MAX == 800


def test_comparar_cuenta_aciertos_y_sobrantes():
    derivado = {"apertura": [{"id": 1}, {"id": 2}, {"id": 9}]}
    r = M.comparar(derivado, ["1", "2", "3"])
    assert r["aciertos"] == 2 and r["de"] == 3
    assert r["faltan"] == [3] and r["sobran"] == [9]


def test_guardar_y_cargar_dan_la_vuelta(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "CARPETA", str(tmp_path))
    d = M.derivar([_fila(1)], catalogo=CATALOGO_FALSO, min_muestra=1)
    ruta = M.guardar(6, d, extra={"fuente": "prueba"})
    assert os.path.exists(ruta)
    vuelto = M.cargar(6)
    assert vuelto["hero_id"] == 6 and vuelto["fuente"] == "prueba"
    assert vuelto["apertura"][0]["id"] == 1


def test_sin_meta_guardado_devuelve_none(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "CARPETA", str(tmp_path))
    assert M.cargar(999) is None

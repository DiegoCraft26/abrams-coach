"""El corpus de compras y el artefacto de valor: contrato de datos del motor v2.

Lo que se fija aquí:

- el inventario se reconstruye exacto (una compra cuenta si ocurrió antes y no se vendió);
- el corpus congelado lleva el hash de la base, y si la base cambia el artefacto deja de
  usarse (modo CIEGO) en vez de mentir con números de otra muestra;
- la evidencia nunca se sirve sin intervalo, sin muestra o con etiqueta "sin señal".
"""
import json
import os
import sys

import numpy as np
import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import valor                        # noqa: E402
from herramientas.lab import corpus            # noqa: E402


# --- corpus -------------------------------------------------------------------
def _datos_sinteticos():
    """Dos compras en una partida, la segunda después de vender la primera."""
    return {
        "ids": ["a", "b", "c"],
        "match": np.array([1, 1, 2], dtype=np.int64),
        "slot": np.array([0, 0, 0], dtype=np.int16),
        "orden": np.array([1, 2, 1], dtype=np.int16),
        "t": np.array([100.0, 300.0, 120.0], dtype=np.float32),
        "item": np.array([0, 1, 2], dtype=np.int32),
        "coste": np.array([800, 1600, 3200], dtype=np.int32),
        "nw": np.array([1000, 3000, 2000], dtype=np.int64),
        "vendido_t": np.array([200.0, 0.0, 0.0], dtype=np.float32),
        "y": np.array([1, 1, 0], dtype=np.int8),
    }


def test_el_inventario_cuenta_lo_que_sigue_en_la_mochila():
    cat = {"a": {"coste": 800, "activo": False},
           "b": {"coste": 1600, "activo": True},
           "c": {"coste": 3200, "activo": False}}
    d = corpus.con_inventario(_datos_sinteticos(), cat)
    # Primera compra: nada dentro. Segunda: 'a' se vendió a los 200 s, así que tampoco.
    assert list(d["n_items"]) == [0, 0, 0]
    assert list(d["inversion"]) == [0, 0, 0]


def test_el_inventario_cuenta_lo_no_vendido():
    datos = _datos_sinteticos()
    datos["vendido_t"] = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    cat = {"a": {"coste": 800, "activo": False},
           "b": {"coste": 1600, "activo": True},
           "c": {"coste": 3200, "activo": False}}
    d = corpus.con_inventario(datos, cat)
    assert list(d["n_items"]) == [0, 1, 0]
    assert list(d["inversion"]) == [0, 800, 0]
    assert list(d["n_activos"]) == [0, 0, 0]


def test_las_franjas_cortan_en_15_y_30_minutos():
    fr = corpus.franja(np.array([0.0, 899.0, 900.0, 1799.0, 1800.0, 5000.0]))
    assert list(fr) == [0, 0, 1, 1, 2, 2]


def test_el_shortlist_prioriza_lo_que_se_compra():
    """Solo entran acciones con soporte: el ítem sin compras no puede estar."""
    datos = _datos_sinteticos()
    datos["item"] = np.array([0, 0, 1], dtype=np.int32)      # 0 dos veces, 1 una
    corto = corpus.shortlist(datos, por_franja=2)
    assert corto[0][0] == 0
    assert set(corto[0]).issubset({0, 1})


# --- artefacto y honestidad ----------------------------------------------------
def _artefacto(item_id="123"):
    return {
        "generado": "2026-11-18T00:00:00-0600",
        "corpus": {"sha256_db": "abc", "generado": "2026-11-18"},
        "metodo": {"semilla": 7, "bootstrap": "200 réplicas"},
        "items": {
            item_id: {
                "nombre": "Item",
                "efecto_pp": 1.8,
                "ic90": [0.4, 3.2],
                "ic95": [0.1, 3.5],
                "lcb90": 0.4,
                "n": 3000,
                "n_partidas": 2700,
                "etiqueta": "medido",
                "evalue": 1.2,
                "oos_signo": True,
                "mde_pp": 1.1,
            }
        },
    }


def _montar(tmp_path, monkeypatch, doc=None, sha="abc"):
    ruta = tmp_path / "modelo_v2.json"
    ruta.write_text(json.dumps(doc if doc is not None else _artefacto()),
                    encoding="utf-8")
    (tmp_path / "corpus.json").write_text(json.dumps({"sha256_db": sha}),
                                          encoding="utf-8")
    monkeypatch.setattr(valor, "RUTA", str(ruta))
    monkeypatch.setattr(valor, "RUTA_CORPUS", str(tmp_path / "corpus.json"))
    monkeypatch.setattr(valor, "_cache", {"ruta": None, "doc": None, "error": None})


def test_sin_artefacto_el_modo_es_ciego(tmp_path, monkeypatch):
    monkeypatch.setattr(valor, "RUTA", str(tmp_path / "no-existe.json"))
    monkeypatch.setattr(valor, "RUTA_CORPUS", str(tmp_path / "no-existe2.json"))
    monkeypatch.setattr(valor, "_cache", {"ruta": None, "doc": None, "error": None})
    assert valor.cargar() is None
    assert valor.modo() == "CIEGO"
    assert valor.evidencia("123") is None


def test_si_el_corpus_cambia_no_se_usa_el_artefacto(tmp_path, monkeypatch):
    """Los números describen otra base: usarlos sería mentir con otro corpus."""
    _montar(tmp_path, monkeypatch, sha="otro-hash")
    assert valor.cargar() is None
    assert valor.modo() == "CIEGO"
    assert "no coincide" in (valor.motivo() or "")


def test_la_evidencia_lleva_intervalo_y_muestra(tmp_path, monkeypatch):
    _montar(tmp_path, monkeypatch)
    ev = valor.evidencia("123")
    assert ev["ic90"] == [0.4, 3.2]
    assert ev["n_partidas"] == 2700
    assert ev["etiqueta"] == "medido"
    assert ev["fuente"] == "modelo_v2"


def test_sin_senal_no_se_sirve_evidencia(tmp_path, monkeypatch):
    doc = _artefacto()
    doc["items"]["123"]["etiqueta"] = "sin_senal"
    _montar(tmp_path, monkeypatch, doc)
    assert valor.evidencia("123") is None


def test_el_desempate_solo_mueve_empates_con_cota_positiva(tmp_path, monkeypatch):
    doc = _artefacto("a")
    doc["items"]["b"] = {**_artefacto()["items"]["123"], "lcb90": 1.5, "efecto_pp": 2.5}
    _montar(tmp_path, monkeypatch, doc)
    filas = [{"id": "a", "score": 10.0}, {"id": "b", "score": 9.8}]
    movidas, movido = valor.desempatar(filas, 0.5)
    assert movidas[0]["id"] == "b" and movido


def test_no_reordena_si_la_diferencia_no_es_empate(tmp_path, monkeypatch):
    doc = _artefacto("a")
    doc["items"]["b"] = {**_artefacto()["items"]["123"], "lcb90": 1.5}
    _montar(tmp_path, monkeypatch, doc)
    filas = [{"id": "a", "score": 10.0}, {"id": "b", "score": 5.0}]
    movidas, movido = valor.desempatar(filas, 0.5)
    assert movidas[0]["id"] == "a" and movido is None


def test_el_resumen_dice_cuantos_estan_medidos(tmp_path, monkeypatch):
    _montar(tmp_path, monkeypatch)
    r = valor.resumen()
    assert r["modo"] == "MEDIDO" and r["medidos"] == 1

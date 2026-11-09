"""El inventario propio: procedencia, edad y la guardia de espectador.

Lo que se prueba es la regla que evita el error caro: recomendar una compra sobre una
partida que no es la tuya, o sobre una tienda leída a medias.
"""
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from coach import inventario_propio as inv  # noqa: E402

ITEM = "1548066885"


def _limpio(tmp_path, monkeypatch):
    destino = tmp_path / "inventario.json"
    monkeypatch.setattr(inv, "RUTA", str(destino))
    inv.reiniciar_para_pruebas()
    return destino


def test_guarda_y_devuelve_para_el_panel(tmp_path, monkeypatch):
    _limpio(tmp_path, monkeypatch)
    assert inv.actualizar([ITEM], {"weapon": 2, "vitality": 1}, confianza=0.8)
    estado = inv.como_estado()
    assert estado["inventario"] == [{"id": ITEM}]
    assert estado["slots"]["weapon"] == {"usados": 2, "total": 4}
    assert estado["confianza"] == 0.8
    assert estado["fuente"] == "tienda"


def test_espectando_no_toca_tu_inventario(tmp_path, monkeypatch):
    _limpio(tmp_path, monkeypatch)
    assert inv.actualizar([ITEM], {"weapon": 1}, espectando=False)
    assert inv.actualizar(["999"], {"weapon": 4}, espectando=True) is False
    assert [i["id"] for i in inv.como_estado()["inventario"]] == [ITEM]


def test_sin_items_ni_slots_no_guarda_nada(tmp_path, monkeypatch):
    _limpio(tmp_path, monkeypatch)
    assert inv.actualizar([], {}) is False
    assert inv.estado()["hay"] is False


def test_el_inventario_viejo_no_se_usa_para_decidir(tmp_path, monkeypatch):
    _limpio(tmp_path, monkeypatch)
    inv.actualizar([ITEM], {"weapon": 1}, ts=time.time() - 400)
    assert inv.leer(max_edad_s=180) is None
    # Pero se puede mirar para saber que existe y pedir abrir la tienda.
    estado = inv.estado()
    assert estado["hay"] is True
    assert estado["utilizable"] is False
    assert "abre la tienda" in (estado["aviso"] or "")


def test_sobrevive_a_un_reinicio_del_coach(tmp_path, monkeypatch):
    destino = _limpio(tmp_path, monkeypatch)
    inv.actualizar([ITEM], {"spirit": 2})
    assert destino.exists()
    inv.reiniciar_para_pruebas()          # como si el proceso arrancara de cero
    assert [i["id"] for i in inv.como_estado()["inventario"]] == [ITEM]


def test_descarta_basura_en_los_ids(tmp_path, monkeypatch):
    _limpio(tmp_path, monkeypatch)
    inv.actualizar([ITEM, "no-es-un-id", None], {"weapon": 9})
    datos = inv.como_estado()
    assert [i["id"] for i in datos["inventario"]] == [ITEM]
    assert "weapon" not in datos["slots"]   # 9 huecos no existen


def test_archivo_corrupto_no_revienta(tmp_path, monkeypatch):
    destino = _limpio(tmp_path, monkeypatch)
    destino.write_text("{roto", encoding="utf-8")
    inv.reiniciar_para_pruebas()
    assert inv.como_estado() is None
    assert inv.estado()["hay"] is False

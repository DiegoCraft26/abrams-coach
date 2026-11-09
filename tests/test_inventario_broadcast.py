"""Criterio de la Fase 2: comprar y vender se refleja en el inventario publicado.

Con broadcast, el inventario llega en cada tick; lo que se prueba aquí es que el estado
publicado cambia cuando cambian los ítems del jugador y que los huecos no se inventan.
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from coach import nucleo_vivo as NV  # noqa: E402
from coach.motor_api import Motor  # noqa: E402

MOTOR = Motor()
CATALOGO = MOTOR.conoc["items"]


def _dos_items(slot="weapon", cuantos=2):
    return [iid for iid, d in CATALOGO.items() if d.get("slot") == slot][:cuantos]


def _jugador(cuenta, equipo, heroe, almas, items=None):
    return {"cuenta": cuenta, "equipo": equipo, "heroe": heroe, "almas": almas,
            "neto": almas + 300, "bajas": 1, "muertes": 0, "asistencias": 2,
            "items": list(items or [])}


def _estado(items):
    yo = _jugador(1, 2, "Abrams", 2400, items)
    return {"tick": 900, "t": 420.0,
            "jugadores": [yo, _jugador(2, 3, "Haze", 2100)],
            "yo": yo, "aliados": [yo], "enemigos": [_jugador(2, 3, "Haze", 2100)]}


def test_el_inventario_del_broadcast_llega_al_estado():
    items = _dos_items()
    crudo = NV.estado_desde_vivo(_estado(items), cuenta=1)
    assert crudo["yo"]["items"] == items


def test_comprar_un_item_cambia_el_inventario_publicado():
    antes = _dos_items(cuantos=1)
    despues = _dos_items(cuantos=2)
    primero = MOTOR.analizar_dict(NV.estado_desde_vivo(_estado(antes), cuenta=1))
    segundo = MOTOR.analizar_dict(NV.estado_desde_vivo(_estado(despues), cuenta=1))
    assert primero["slots"]["weapon"]["usados"] == 1
    assert segundo["slots"]["weapon"]["usados"] == 2
    assert segundo["slots"]["weapon"]["libres"] == 2


def test_vender_deja_el_hueco_libre():
    con_dos = _dos_items(cuantos=2)
    con_uno = _dos_items(cuantos=1)
    a = MOTOR.analizar_dict(NV.estado_desde_vivo(_estado(con_dos), cuenta=1))
    b = MOTOR.analizar_dict(NV.estado_desde_vivo(_estado(con_uno), cuenta=1))
    assert a["slots"]["weapon"]["usados"] > b["slots"]["weapon"]["usados"]
    assert b["slots"]["weapon"]["libres"] > a["slots"]["weapon"]["libres"]


def test_sin_items_no_se_inventa_inventario():
    crudo = NV.estado_desde_vivo(_estado([]), cuenta=1)
    salida = MOTOR.analizar_dict(crudo)
    assert crudo["yo"]["items"] == []
    assert salida["slots"]["weapon"]["usados"] == 0
    assert not salida.get("inventario")


def test_el_pie_dice_la_fase_del_juego():
    from coach.ui.componentes.pie import texto_fuente

    assert texto_fuente({"fuente": "en_vivo", "fase_juego": "GameInProgress"}) == \
        "fuente en vivo · fase en partida"
    assert texto_fuente({"fuente": "pantalla"}) == "fuente pantalla"
    assert "menu" not in texto_fuente({"fuente": "pantalla"}).lower()


def test_el_pie_traduce_fases_desconocidas_sin_romperse():
    from coach.ui.componentes.pie import texto_fuente

    assert "fase algo raro" in texto_fuente({"fuente": "x", "fase_juego": "AlgoRaro"})


def test_una_compra_dispara_la_lectura_de_tienda():
    import run as R

    assert R.disparo_por_compra(1200, 400) == "tienda"      # gastó 800
    assert R.disparo_por_compra(400, 1200) is None          # ganó almas, no compró
    assert R.disparo_por_compra(1200, 1100) is None         # 100 no es una compra
    assert R.disparo_por_compra(1000, 900, 3, 4) == "tienda"  # cambió la rejilla
    assert R.disparo_por_compra(None, None) is None
    assert R.disparo_por_compra("mucho", 5) is None

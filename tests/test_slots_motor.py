"""Los huecos por categoría nunca pueden pasar de cuatro.

Regresión del 2026-11-09: el panel mostró «vitalidad 6/4» en una partida real. El
broadcast devuelve el componente y el ítem mejorado a la vez, y el conteo los sumaba.
El juego no puede tener más de 4 huecos por categoría.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from coach.motor_api import Motor  # noqa: E402

MOTOR = Motor()


def _estado(items, almas=3000):
    return {"t": 1200, "yo": {"heroe": "Abrams", "almas": almas, "items": items},
            "aliados": [{"almas": almas}],
            "enemigos": [{"heroe": "haze", "almas": almas}], "confianza": 1.0}


def _items_de(slot, cuantos):
    catalogo = MOTOR.conoc["items"]
    return [iid for iid, d in catalogo.items() if d.get("slot") == slot][:cuantos]


def test_seis_items_de_vitalidad_se_publican_como_cuatro():
    resultado = MOTOR.analizar_dict(_estado(_items_de("vitality", 6)))
    vitality = resultado["slots"]["vitality"]
    assert vitality["usados"] == 4
    assert vitality["total"] == 4
    assert vitality["libres"] == 0
    # El número crudo queda a la vista para poder revisar la fuente.
    assert vitality["brutos"] == 6


def test_un_inventario_normal_no_se_toca():
    resultado = MOTOR.analizar_dict(_estado(_items_de("weapon", 2)))
    assert resultado["slots"]["weapon"]["usados"] == 2
    assert resultado["slots"]["weapon"]["brutos"] == 2


def test_sin_items_todo_en_cero():
    resultado = MOTOR.analizar_dict(_estado([]))
    for categoria in ("weapon", "vitality", "spirit"):
        assert resultado["slots"][categoria]["usados"] == 0

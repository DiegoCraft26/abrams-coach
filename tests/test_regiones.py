"""Las regiones del HUD tienen que apuntar a algo.

El 2026-11-09 la zona `almas` apuntaba a un trozo de pantalla donde solo había un «2»
suelto: la visión lo leyó como «2 almas» y el OCR local devolvía basura. Una región mal
calibrada no falla: miente. Por eso se comprueban aquí.
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

RUTA = RAIZ / "config" / "regiones.json"
REGIONES = json.loads(RUTA.read_text(encoding="utf-8"))


def _regiones() -> dict:
    return {k: v for k, v in REGIONES.items()
            if isinstance(v, list) and len(v) == 4 and all(isinstance(x, (int, float))
                                                           for x in v)}


def test_hay_regiones_y_son_fracciones_validas():
    regiones = _regiones()
    assert regiones, "el archivo no tiene ninguna región utilizable"
    for nombre, (x, y, ancho, alto) in regiones.items():
        assert 0 <= x < 1 and 0 <= y < 1, f"{nombre}: origen fuera de la pantalla"
        assert 0 < ancho <= 1 and 0 < alto <= 1, f"{nombre}: tamaño imposible"
        assert x + ancho <= 1.001 and y + alto <= 1.001, f"{nombre}: se sale del área"


def test_la_zona_del_reloj_esta_arriba_en_el_centro():
    x, y, ancho, alto = _regiones()["tiempo"]
    assert 0.40 <= x <= 0.55, "el reloj va arriba al centro"
    assert y <= 0.02
    assert ancho <= 0.15 and alto <= 0.05


def test_la_zona_del_oro_esta_abajo_a_la_izquierda():
    x, y, ancho, alto = _regiones()["oro"]
    assert x <= 0.10 and y >= 0.75
    assert ancho <= 0.15 and alto <= 0.08


def test_la_zona_de_almas_no_es_la_vieja_que_mintio():
    # La vieja era [0.36, 0.93, 0.12, 0.045]: un trozo de HUD sin números.
    assert _regiones()["almas"] != [0.36, 0.93, 0.12, 0.045]
    x, y, _, _ = _regiones()["almas"]
    assert y <= 0.10, "las almas de equipo se leen arriba, junto al reloj"


def test_la_rejilla_de_items_cabe_en_la_esquina():
    x, y, ancho, alto = _regiones()["mis_items"]
    assert x <= 0.02 and y >= 0.85
    assert ancho <= 0.20 and alto <= 0.12

"""El HUD no puede arrancar la captura compartida del escritorio: no la lee nadie.

Regresión del 2026-11-18: `arrancar_hud` llamaba a `captura.global_()` con intervalo
0.4 s. Ese singleton capturaba los dos monitores (4480×1440) 2,3 veces por segundo y el
cuadro no lo consumía nadie — el HUD usa `MarcoPerezoso` y `leer_actual()` no tiene
llamadas. Medido: 39 ms por captura → ~92 ms de CPU/s (9 % de un núcleo) más 2,3
readbacks del compositor por segundo, gratis para nadie.

También fija que `--intervalo` (ABRAMS_INTERVALO) llega a la cadencia del OCR: antes había
un piso duro de 2 s y la opción no cambiaba nada.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import nucleo_vivo  # noqa: E402
from coach.fuentes import captura  # noqa: E402


class _Arg:
    def __init__(self, intervalo=1.0):
        self.pantalla = True
        self.sin_hud = False
        self.intervalo = intervalo


def _arrancar(monkeypatch, intervalo):
    """Arranca el HUD sin hilo de verdad y devuelve el `hud_cfg` que recibió."""
    visto = {}

    class _Hilo:
        def __init__(self, target=None, args=(), **kw):
            visto["target"] = target
            visto["args"] = args

        def start(self):
            visto["arrancado"] = True

    monkeypatch.setattr(nucleo_vivo.threading, "Thread", _Hilo)
    nucleo_vivo.arrancar_hud(_Arg(intervalo), {}, {"hud_ocr": True})
    return visto


def test_no_arranca_la_captura_del_escritorio(monkeypatch):
    antes = captura._INSTANCIA
    _arrancar(monkeypatch, 1.0)
    assert captura._INSTANCIA is antes, "el HUD no puede encender captura.global_()"


def test_si_arranca_el_hilo_del_hud(monkeypatch):
    visto = _arrancar(monkeypatch, 1.0)
    assert visto.get("arrancado") is True
    assert visto["target"] is nucleo_vivo.hilo_hud


def test_el_intervalo_llega_al_hud(monkeypatch):
    assert _arrancar(monkeypatch, 1.0)["args"][1]["intervalo_min_s"] == 2.0
    assert _arrancar(monkeypatch, 4.0)["args"][1]["intervalo_min_s"] == 4.0

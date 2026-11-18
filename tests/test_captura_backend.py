"""La captura compartida funciona con cualquier backend, incluido el que no existe aún.

Windows necesita su propia captura (DXGI/mss) y aquí no hay Windows. Lo que sí se puede
verificar es la pieza que ambos comparten: el hilo publica el último cuadro, cuenta
fallos y no se cae cuando el backend falla o no tiene cuadro nuevo.
"""
import pathlib
import sys
import time

import pytest
from PIL import Image

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from coach.fuentes import captura, captura_windows  # noqa: E402


def _esperar(cond, limite=2.0):
    fin = time.time() + limite
    while time.time() < fin:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_publica_el_cuadro_del_backend():
    imagen = Image.new("RGB", (16, 9), (10, 20, 30))
    c = captura.CapturaCompartida(intervalo=0.01, backend=lambda: imagen).arrancar()
    try:
        assert _esperar(lambda: c.capturas > 0)
        cuadro, edad = c.ultimo()
        assert cuadro is not None and cuadro.size == (16, 9)
        assert edad is not None and edad < 1
        assert c.metricas()["ms_mediana"] is not None
    finally:
        c.parar()


def test_backend_sin_cuadro_no_publica():
    c = captura.CapturaCompartida(intervalo=0.01, backend=lambda: None).arrancar()
    try:
        time.sleep(0.1)
        assert c.capturas == 0
        assert c.ultimo() == (None, None)
    finally:
        c.parar()


def test_backend_que_falla_cuenta_y_sigue_vivo():
    def roto():
        raise RuntimeError("pantalla bloqueada")
    c = captura.CapturaCompartida(intervalo=0.01, backend=roto).arrancar()
    try:
        assert _esperar(lambda: c.fallos > 0)
        assert "pantalla bloqueada" in (c.ultimo_error or "")
        assert c._hilo.is_alive()
    finally:
        c.parar()


def test_windows_sin_backend_lanza_con_motivo(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(RuntimeError) as exc:
        captura.CapturaCompartida()
    assert "Windows" in str(exc.value)


def test_windows_no_disponible_en_linux():
    if sys.platform.startswith("win"):
        pytest.skip("esto es Windows de verdad")
    with pytest.raises(RuntimeError):
        captura_windows.backend()
    assert captura_windows.disponible() is False

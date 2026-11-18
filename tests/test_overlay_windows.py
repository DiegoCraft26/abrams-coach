"""El overlay de Windows: lo que se puede verificar sin Windows.

Lo puro es real y se prueba aquí: la combinación de estilos, la posición por esquina y
que el módulo se importe en Linux. Lo que necesita una máquina Windows (que se componga
encima del juego, que los clics pasen) NO se prueba, y el módulo lo dice.
"""
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from coach.ui import overlay_windows as ow  # noqa: E402


def test_estilos_incluyen_lo_que_hace_falta():
    e = ow.estilos_ex()
    for flag in (ow.WS_EX_LAYERED, ow.WS_EX_TRANSPARENT, ow.WS_EX_NOACTIVATE,
                 ow.WS_EX_TOOLWINDOW):
        assert e & flag, f"falta 0x{flag:08X}"
    # TOPMOST no va en los estilos: la documentación manda SetWindowPos.
    assert not (e & ow.WS_EX_TOPMOST)


def test_posicion_en_las_seis_esquinas():
    pantalla, tamano, m = (2560, 1440), (440, 132), 28
    assert ow.posicion(pantalla, tamano, "arriba-izquierda", m) == (28, 28)
    assert ow.posicion(pantalla, tamano, "arriba-derecha", m) == (2560 - 440 - 28, 28)
    assert ow.posicion(pantalla, tamano, "abajo-izquierda", m) == (28, 1440 - 132 - 28)
    assert ow.posicion(pantalla, tamano, "abajo-derecha", m) == (2560 - 440 - 28, 1440 - 132 - 28)
    assert ow.posicion(pantalla, tamano, "centro-derecha", m) == (2560 - 440 - 28, (1440 - 132) // 2)
    assert ow.posicion(pantalla, tamano, "centro-izquierda", m) == (28, (1440 - 132) // 2)


def test_posicion_no_sale_de_pantalla():
    # Tarjeta más grande que la pantalla: se pega a la esquina, no da negativo.
    assert ow.posicion((200, 100), (440, 132), "centro-derecha", 28) == (0, 0)


def test_en_linux_no_esta_disponible_y_falla_con_motivo():
    if sys.platform.startswith("win"):
        pytest.skip("esto es Windows de verdad")
    assert ow.disponible() is False
    with pytest.raises(RuntimeError) as exc:
        ow.VentanaOverlay()
    assert "Windows" in str(exc.value)

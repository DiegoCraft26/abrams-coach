"""El panel no promete precisión de oro que no tiene.

Contrato fijado el 2026-11-18: «faltan» y «te alcanza» salieron del panel, del overlay y
de la tarjeta porque dependen de las almas del momento, que llegan del broadcast con
retraso o de una lectura OCR que falla. Si vuelven, esta prueba falla.
"""
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from coach.ui.web import PAGINA  # noqa: E402


def test_el_panel_no_dice_te_alcanza():
    # La cadena exacta que se pintaba junto al precio. El comentario del código puede
    # nombrar la regla; lo que no puede volver es el texto que ve el jugador.
    assert "ya te alcanza" not in PAGINA
    assert f'" · ya te alcanza"' not in PAGINA


def test_el_panel_no_estima_faltan():
    assert "faltan ~" not in PAGINA


def test_el_panel_conserva_el_precio_de_lista():
    assert 'id="rec"' in PAGINA
    assert "costo" in PAGINA

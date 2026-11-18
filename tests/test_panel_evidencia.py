"""La tarjeta de recomendación y su línea de evidencia.

Lo que se fija: la evidencia del motor v2 solo se pinta cuando hay efecto, intervalo y
muestra; sin esos tres datos la línea desaparece. Mostrar un punto sin intervalo está
prohibido por la especificación, y este es el sitio donde se cumple.
"""
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.ui.componentes.recomendacion import RecommendationCard  # noqa: E402

_APP = None


def _ventana():
    """Una ventana base: GTK no deja usar widgets sin un Gtk.Application activo."""
    global _APP
    if _APP is None:
        _APP = Gtk.Application(application_id="gg.diego.abramscoach.pruebaevidencia")
        _APP.register(None)
        _APP.activate()
    return _APP


def _estado(evidencia):
    return {
        "listo": True,
        "fuente": "simulado",
        "decision": {"accion": "COMPRAR", "motivo": "es la siguiente pieza del camino"},
        "recomendaciones": [{
            "id": "2407781327", "nombre": "Colossus", "costo": 6400,
            "razones": ["es la siguiente pieza del camino"],
            "evidencia": evidencia,
        }],
        "evidencia": evidencia,
    }


def _texto(card):
    return card.lbl_evidencia.get_label()


def _construir():
    _ventana()
    return RecommendationCard()


def test_la_evidencia_se_pinta_con_intervalo_y_muestra():
    card = _construir()
    card.actualizar(_estado({
        "efecto_pp": 3.9, "ic90": [2.6, 5.2], "n_partidas": 4092,
        "etiqueta": "medido", "evalue": 1.36,
    }))
    assert card.lbl_evidencia.get_visible()
    texto = _texto(card)
    assert "medido" in texto and "+3.9 pp" in texto
    assert "4,092" in texto or "4092" in texto
    assert "E 1.36" in texto


def test_sin_muestra_no_hay_evidencia():
    card = _construir()
    card.actualizar(_estado({"efecto_pp": 3.9, "ic90": [2.6, 5.2], "etiqueta": "medido"}))
    assert not card.lbl_evidencia.get_visible()


def test_sin_intervalo_no_hay_evidencia():
    card = _construir()
    card.actualizar(_estado({"efecto_pp": 3.9, "n_partidas": 4092,
                             "etiqueta": "medido"}))
    assert not card.lbl_evidencia.get_visible()


def test_sin_evidencia_la_linea_desaparece():
    card = _construir()
    card.actualizar(_estado({"efecto_pp": 3.9, "ic90": [2.6, 5.2],
                             "n_partidas": 4092, "etiqueta": "medido"}))
    assert card.lbl_evidencia.get_visible()
    card.actualizar(_estado(None))
    assert not card.lbl_evidencia.get_visible()

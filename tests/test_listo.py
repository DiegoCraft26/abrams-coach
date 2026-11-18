"""El chequeo previo: dice qué falta y cómo arreglarlo, sin fingir lo que no comprueba."""
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas"))

import listo  # noqa: E402


def fila(nombre, ok, detalle="", arreglo=""):
    return {"nombre": nombre, "ok": ok, "detalle": detalle, "arreglo": arreglo}


def test_todo_listo_lo_dice():
    r = {"filas": [fila("cuenta", True, "123")], "faltan": [], "listo": True}
    t = listo.texto(r)
    assert "todo listo para jugar" in t
    assert "ok    cuenta" in t


def test_falta_nombra_el_arreglo():
    r = {"filas": [fila("puerto", False, "8090 ocupado", "abrams-coach parar")],
         "faltan": ["puerto"], "listo": False}
    t = listo.texto(r)
    assert "falta: puerto" in t
    assert "→ abrams-coach parar" in t


def test_siempre_avisa_lo_que_no_se_puede_comprobar():
    r = {"filas": [], "faltan": [], "listo": True}
    assert "no se puede comprobar sin abrirlo" in listo.texto(r)


def test_evaluar_trae_los_ocho_controles():
    r = listo.evaluar()
    nombres = [f["nombre"] for f in r["filas"]]
    assert nombres == ["cuenta", "red", "clave API", "captura", "overlay", "puerto",
                       "disco", "silencio", "objetivo"]
    assert isinstance(r["listo"], bool)

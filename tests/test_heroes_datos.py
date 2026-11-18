"""Los datos por héroe cargan, y el que falta no rompe la decisión.

`data/heroes/` tiene Abrams (de guía) y tres héroes cuya apertura se derivó de `lab.db`
(2026-11-18). Hitos y fases de esos tres no se derivaron: usan el respaldo de Abrams y el
JSON lo dice. Un héroe sin archivo también cae a Abrams: la app nunca se queda sin decidir.
"""
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from coach.decision import heroe  # noqa: E402

ESPERADOS = {"abrams": "Abrams", "haze": "Haze", "ratking": "Rat King", "graves": "Graves"}


def test_los_cuatro_heroes_cargan_con_su_apertura():
    for clave, nombre in ESPERADOS.items():
        h = heroe.cargar(clave)
        assert h.nombre == nombre, clave
        assert len(h.apertura) == 5, clave


def test_el_heroe_sin_archivo_cae_a_abrams():
    h = heroe.cargar("heroe-que-no-existe")
    assert h.nombre == "Abrams"


def test_la_apertura_derivada_dice_de_donde_sale():
    h = heroe.cargar("haze")
    fuente = h.datos["apertura"]["fuente"]
    assert "lab.db" in fuente and "partidas" in fuente
    assert h.datos["apertura"]["fecha"]


def test_hitos_y_fases_usan_el_respaldo_si_faltan():
    import json
    crudo = json.loads((RAIZ / "data" / "heroes" / "haze.json").read_text(encoding="utf-8"))
    assert "hitos_almas" not in crudo and "fases" not in crudo   # no se inventaron
    h = heroe.cargar("haze")
    assert h.fases[0][0] == "EARLY"
    assert len(h.hitos) == 2                                     # respaldo de Abrams

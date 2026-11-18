"""El panel sin partida enseña la última nota, y solo cuando toca.

La nota la escribe el vigilante en `salida/ultima_nota.txt` al cerrar Deadlock. El
servidor la inyecta en `/api/estado` solo cuando no hay partida (`listo: false`) y solo
si es reciente; una nota de hace días no se enseña como si fuera de ahora.
"""
import os
import pathlib
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from coach import servidor  # noqa: E402


def _nota(tmp_path, texto="139293743 · Abrams · victoria\n3 200 al min 10:37 ✓"):
    ruta = tmp_path / "ultima_nota.txt"
    ruta.write_text(texto, encoding="utf-8")
    return str(ruta)


def test_lee_la_nota_reciente(tmp_path):
    nota, edad = servidor.ultima_nota(_nota(tmp_path))
    assert nota.startswith("139293743")
    assert edad is not None and edad < 5


def test_no_lee_si_es_vieja(tmp_path):
    ruta = pathlib.Path(_nota(tmp_path))
    viejo = time.time() - 3 * 86400
    os.utime(ruta, (viejo, viejo))
    assert servidor.ultima_nota(str(ruta)) == (None, None)


def test_sin_archivo_no_hay_nota(tmp_path):
    assert servidor.ultima_nota(str(tmp_path / "no_existe.txt")) == (None, None)


def test_estado_publico_la_pone_solo_sin_partida(monkeypatch):
    monkeypatch.setattr(servidor, "ultima_nota", lambda *a, **k: ("nota de prueba", 3))
    d = servidor.estado_publico({"listo": False}, 0.5)
    assert d["ultima_nota"] == "nota de prueba"
    d2 = servidor.estado_publico({"listo": True}, 0.5)
    assert "ultima_nota" not in d2


def test_panel_muestra_la_nota_cuando_existe():
    from coach.ui.web import PAGINA
    assert "ultima_nota" in PAGINA
    assert "última partida" in PAGINA


def test_objetivo_de_sesion_se_publica_sin_partida(tmp_path):
    import json
    ruta = tmp_path / "plan_actual.json"
    ruta.write_text(json.dumps({"regla": "muertes", "meta": 6, "partidas": 5,
                                "necesarias": 3, "desde": 0.0}), encoding="utf-8")
    obj = servidor.objetivo_sesion(str(ruta))
    assert obj["texto"] == "3 de 5 con ≤6 muertes"


def test_sin_objetivo_no_se_publica(tmp_path):
    assert servidor.objetivo_sesion(str(tmp_path / "nada.json")) is None


def test_estado_publico_incluye_objetivo_solo_sin_partida(monkeypatch, tmp_path):
    import json
    ruta = tmp_path / "plan_actual.json"
    ruta.write_text(json.dumps({"regla": "participacion", "meta": 0.4, "partidas": 5,
                                "necesarias": 3}), encoding="utf-8")
    original = servidor.objetivo_sesion
    monkeypatch.setattr(servidor, "objetivo_sesion",
                        lambda *a, **k: original(str(ruta)))
    d = servidor.estado_publico({"listo": False}, 0.5)
    assert "≥0.4" in d["objetivo"]["texto"]
    assert "objetivo" not in servidor.estado_publico({"listo": True}, 0.5)


def test_no_publica_un_objetivo_de_3200(tmp_path):
    import json
    ruta = tmp_path / "plan_actual.json"
    ruta.write_text(json.dumps({"regla": "min3200", "meta": 12, "partidas": 5,
                                "necesarias": 3}), encoding="utf-8")
    assert servidor.objetivo_sesion(str(ruta)) is None

"""Modo pantalla: lo que se publica con y sin inventario leído en la tienda.

La regla que se defiende aquí: sin inventario, pasados 10 minutos solo se dice el reloj;
con el inventario de la tienda, el motor sí decide y lo dice con su procedencia.
"""
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from coach import nucleo_vivo as NV  # noqa: E402
from coach import servidor as S  # noqa: E402


class EstadoFalso:
    def __init__(self):
        self.ultimo = None

    def publicar(self, datos):
        self.ultimo = datos


def _hud(t=700):
    return {"t": t, "oro": 700, "ts": time.time()}


def _analizar(crudo):
    return {"listo": True, "plan": [{"id": "1"}], "fuente": "pantalla",
            "decision": {"estado": "COMPRAR"}, "notas": []}


def _publicar(monkeypatch, inventario=None, t=700):
    # El estabilizador de reloj guarda estado entre llamadas: sin resetear, el reloj de
    # un caso contamina al siguiente (que es justo lo que hace en la app real).
    NV._RELOJ.update({"t": None, "cand": None, "veces": 0})
    falso = EstadoFalso()
    monkeypatch.setattr(NV.servidor, "EST", falso)
    assert NV.publicar_pantalla(_hud(t), _analizar, None, None, inventario=inventario)
    return falso.ultimo


def test_sin_inventario_pasados_10_min_solo_el_reloj(monkeypatch):
    datos = _publicar(monkeypatch)
    assert datos["solo_reloj"] is True
    assert datos["decision"] is None
    assert "sin broadcast" in " ".join(datos["notas"])


def test_con_inventario_el_motor_decide_y_lo_dice(monkeypatch):
    inventario = {"inventario": [{"id": "1548066885"}],
                  "slots": {"weapon": {"usados": 2, "total": 4}},
                  "fuente": "tienda", "confianza": 0.8, "edad_s": 12}
    datos = _publicar(monkeypatch, inventario=inventario)
    assert datos.get("solo_reloj") is not True
    assert datos["decision"] == {"estado": "COMPRAR"}
    assert datos["inventario"] == [{"id": "1548066885"}]
    assert datos["slots"]["weapon"] == {"usados": 2, "total": 4}
    assert "visión" in " ".join(datos["notas"])
    assert "12 s" in " ".join(datos["notas"])


def test_el_inventario_vacio_no_cambia_como_si_no_hubiera(monkeypatch):
    vacio = {"inventario": [], "slots": {}, "fuente": "tienda", "edad_s": 5}
    datos = _publicar(monkeypatch, inventario=vacio)
    assert datos["solo_reloj"] is True


def test_antes_de_10_min_el_plan_sigue_saliendo(monkeypatch):
    datos = _publicar(monkeypatch, t=200)
    assert datos.get("solo_reloj") is not True
    assert datos["plan"] == [{"id": "1"}]

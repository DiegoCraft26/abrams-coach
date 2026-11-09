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


def _publicar(monkeypatch, inventario=None, t=700, vision=None):
    # El estabilizador de reloj guarda estado entre llamadas: sin resetear, el reloj de
    # un caso contamina al siguiente (que es justo lo que hace en la app real).
    NV._RELOJ.update({"t": None, "cand": None, "veces": 0})
    falso = EstadoFalso()
    monkeypatch.setattr(NV.servidor, "EST", falso)
    assert NV.publicar_pantalla(_hud(t), _analizar, None, None, inventario=inventario,
                                vision=vision)
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


def test_el_panel_no_pide_activacion():
    """Una ventana que se presenta se lleva el foco y te saca del juego.

    Regresión del 2026-11-09: el vigilante reabrió el panel en mitad de una ranked y
    `present()` se trajo el foco. Se muestra sin pedir activación y no acepta foco.
    """
    fuente = (RAIZ / "coach" / "ui" / "app.py").read_text(encoding="utf-8")
    assert "win.present()" not in fuente
    assert "win.set_can_focus(False)" in fuente


def test_el_oro_de_la_vision_se_publica_con_su_edad(monkeypatch):
    vision = {"oro": 555, "items_visibles": 1, "reloj_s": 180, "edad_s": 7}
    datos = _publicar(monkeypatch, t=200)
    assert datos["oro"] is None          # sin visión, el HUD no da oro
    datos = _publicar(monkeypatch, t=200, vision=vision)
    assert datos["oro"] == 555
    assert datos["items_visibles"] == 1
    assert "oro leído por visión" in " ".join(datos["notas"])


def test_si_el_hud_da_oro_manda_el_hud(monkeypatch):
    vision = {"oro": 555, "edad_s": 3}
    monkeypatch.setattr(NV, "ORO_PANTALLA_FIABLE", True)
    monkeypatch.setattr(NV, "_oro_estable", lambda valor: 700)
    datos = _publicar(monkeypatch, t=200, vision=vision)
    assert datos["oro"] == 700          # el HUD manda: es más rápido y ya está probado


def test_el_latido_descarta_lecturas_viejas(monkeypatch):
    """Una lectura de hace 2 min no puede pintar el oro de la partida de ahora."""
    import run as R

    class Cola:
        def ultimo(self):
            return {"estado": {"oro": 555, "items_visibles": 5}, "edad_s": 120}

    class Sched:
        def quizas_encolar(self, motivo):
            return False

    assert R._latido_vision(Cola(), Sched(), {"t": 300}) is None


def test_el_latido_pasa_lo_fresco(monkeypatch):
    import run as R

    class Cola:
        def ultimo(self):
            return {"estado": {"oro": 555, "items_visibles": 5}, "edad_s": 12}

    class Sched:
        def quizas_encolar(self, motivo):
            return True

    latido = R._latido_vision(Cola(), Sched(), {"t": 300})
    assert latido["vision"]["oro"] == 555
    assert latido["items_visibles"] == 5

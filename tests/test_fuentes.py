"""Pruebas de coach.fuentes: interfaz, compuesto, validación HUD y robustez.

Sin red y sin juego abierto. Usa fuentes falsas que implementan la misma interfaz.
Ejecutar: python3 tests/test_fuentes.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coach.fuentes.base import EstadoVacio, FuenteDatos, FuenteError
from coach.fuentes.compuesto import FuenteCompuesta
from coach.fuentes.hud_ocr import FuenteHud
from coach.fuentes.simulador import FuenteSimulador

fallos: list[str] = []


def check(nombre: str, cond: bool, detalle: str = "") -> None:
    if cond:
        print(f"  ok   {nombre}")
    else:
        msg = f"  FALLA {nombre}"
        if detalle:
            msg += f"  {detalle}"
        print(msg)
        fallos.append(nombre)


class FuenteFalsa:
    """Fuente controlada para pruebas."""

    def __init__(self, nombre: str, datos=None, disponible: bool = True, exc: Exception | None = None):
        self.nombre = nombre
        self._datos = datos
        self._disponible = disponible
        self._exc = exc
        self.ultimo_error = None
        self.cerrada = False
        self.callbacks = []

    def disponible(self) -> bool:
        if self._exc and isinstance(self._exc, RuntimeError) and str(self._exc) == "disp":
            raise self._exc
        return self._disponible

    def estado(self):
        if self._exc:
            raise self._exc
        return self._datos

    def suscribir(self, fn) -> None:
        self.callbacks.append(fn)

    def cerrar(self) -> None:
        self.cerrada = True


class HudFalsa(FuenteFalsa):
    """HUD falso con validar_contra controlable."""

    def __init__(self, nombre: str, t_hud, coincide: bool | None = None):
        super().__init__(nombre, {"t": t_hud, "oro": 1000, "fuente": "hud", "notas": []})
        self._coincide = coincide
        self.ultimo_descarte = None

    def validar_contra(self, estado_api, tolerancia: float = 0.30) -> bool:
        if self._coincide is not None:
            if not self._coincide:
                self.ultimo_descarte = "HUD descartado por prueba"
            else:
                self.ultimo_descarte = None
            return self._coincide
        # Validación real por reloj, sin leer pantalla.
        if not isinstance(estado_api, dict):
            self.ultimo_descarte = "sin estado de API"
            return False
        t_hud = self._datos.get("t")
        t_api = estado_api.get("t")
        if t_hud is None or t_api is None:
            self.ultimo_descarte = "reloj ausente"
            return False
        ref = max(abs(float(t_api)), 1.0)
        rel = abs(float(t_hud) - float(t_api)) / ref
        if rel > tolerancia:
            self.ultimo_descarte = f"diferencia relativa {rel:.0%} > {tolerancia:.0%}"
            return False
        self.ultimo_descarte = None
        return True


def test_base() -> None:
    print("[base]")
    check("FuenteError es Exception", issubclass(FuenteError, Exception))
    check("EstadoVacio es FuenteError", issubclass(EstadoVacio, FuenteError))
    falsa = FuenteFalsa("x", {"t": 1})
    check("FuenteFalsa satisface FuenteDatos", isinstance(falsa, FuenteDatos))
    sim = FuenteSimulador(t_inicial=100, acelerar=0)
    check("FuenteSimulador satisface FuenteDatos", isinstance(sim, FuenteDatos))
    sim.cerrar()


def test_simulador() -> None:
    print("[simulador]")
    sim = FuenteSimulador(t_inicial=1200.0, acelerar=0)
    d = sim.estado()
    check("devuelve dict", isinstance(d, dict), str(type(d)))
    check("fuente simulada", d.get("fuente") == "simulado", str(d.get("fuente")))
    check("t inicial respetado", d.get("t") == 1200.0, str(d.get("t")))
    check("tiene yo Abrams", (d.get("yo") or {}).get("heroe") == "Abrams")
    check("yo tiene almas", isinstance((d.get("yo") or {}).get("almas"), int))
    check("yo tiene items", isinstance((d.get("yo") or {}).get("items"), list))
    enemigos = d.get("enemigos") or []
    nombres = {e.get("heroe") for e in enemigos if isinstance(e, dict)}
    for h in ("haze", "lash", "seven", "bebop", "wraith"):
        check(f"enemigo real {h}", h in nombres, str(nombres))
    check("tiene confianza", d.get("confianza") is not None)
    sim.cerrar()

    # Sin estado global compartido entre instancias.
    a = FuenteSimulador(t_inicial=100.0, acelerar=0)
    b = FuenteSimulador(t_inicial=500.0, acelerar=0)
    check("instancias independientes A", a.estado().get("t") == 100.0)
    check("instancias independientes B", b.estado().get("t") == 500.0)
    a.cerrar()
    b.cerrar()


def test_compuesto_gana_primera() -> None:
    print("[compuesto: primera válida gana]")
    a = FuenteFalsa("a", {"t": 10, "fuente": "a"})
    b = FuenteFalsa("b", {"t": 20, "fuente": "b"})
    c = FuenteCompuesta([a, b])
    estado = c.estado()
    check("gana la primera", estado.get("fuente") == "a", str(estado))
    check("historial registra ganador", any("gana" in x or "primera" in x for x in c.historial_decisiones),
          str(c.historial_decisiones))
    c.cerrar()


def test_compuesto_esperando() -> None:
    print("[compuesto: estado honesto sin fuentes]")
    c = FuenteCompuesta([])
    estado = c.estado()
    check("devuelve dict", isinstance(estado, dict))
    check("listo False", estado.get("listo") is False, str(estado))
    check("fuente esperando", estado.get("fuente") == "esperando", str(estado))
    check("tiene mensaje", bool(estado.get("mensaje")), str(estado))

    c2 = FuenteCompuesta([FuenteFalsa("nula", None), FuenteFalsa("vacia-off", None, disponible=False)])
    estado2 = c2.estado()
    check("todas inútiles -> esperando", estado2.get("listo") is False)
    check("nunca inventa datos parciales (sin t/almas)", "t" not in estado2 and "almas" not in estado2,
          str(estado2))
    c.cerrar()
    c2.cerrar()


def test_compuesto_excepcion_no_tumba() -> None:
    print("[compuesto: excepciones aisladas]")
    rota = FuenteFalsa("rota", exc=ValueError("boom"))
    buena = FuenteFalsa("buena", {"t": 5, "fuente": "buena"})
    c = FuenteCompuesta([rota, buena])
    estado = c.estado()
    check("usa la fuente sana", estado.get("fuente") == "buena", str(estado))
    check("registra excepción", any("excepción" in x.lower() or "exception" in x.lower() or "ValueError" in x
                                    for x in c.historial_decisiones),
          str(c.historial_decisiones))
    c.cerrar()


def test_hud_validacion_coincide() -> None:
    print("[hud: validación coincide]")
    hud = HudFalsa("hud_ocr", t_hud=1000.0)
    check("coincide con API igual", hud.validar_contra({"t": 1000.0}, tolerancia=0.30) is True)
    check("coincide con 10% diff", hud.validar_contra({"t": 1100.0}, tolerancia=0.30) is True)
    check("coincide con 29% diff", hud.validar_contra({"t": 1290.0}, tolerancia=0.30) is True)
    check("sin descarte", hud.ultimo_descarte is None, str(hud.ultimo_descarte))


def test_hud_validacion_difiere_70() -> None:
    print("[hud: validación difiere 70%]")
    hud = HudFalsa("hud_ocr", t_hud=1700.0)
    ok = hud.validar_contra({"t": 1000.0}, tolerancia=0.30)
    check("rechaza diferencia 70%", ok is False, str(ok))
    check("anota ultimo_descarte", bool(hud.ultimo_descarte), str(hud.ultimo_descarte))


def test_hud_real_con_estado_controlado() -> None:
    print("[hud: FuenteHud real con estado controlado]")
    hud = FuenteHud(nombre="hud_ocr")
    # Controla el reloj sin capturar pantalla.
    hud.estado = lambda: {"t": 1000.0, "oro": 500, "fuente": "hud", "notas": []}  # type: ignore[method-assign]
    check("coincide reloj similar", hud.validar_contra({"t": 1200.0}, tolerancia=0.30) is True)
    check("sin descarte en coincidencia", hud.ultimo_descarte is None, str(hud.ultimo_descarte))
    hud.estado = lambda: {"t": 1700.0, "oro": 500, "fuente": "hud", "notas": []}  # type: ignore[method-assign]
    check("descarta reloj 70% distinto", hud.validar_contra({"t": 1000.0}, tolerancia=0.30) is False)
    check("motivo en ultimo_descarte", bool(hud.ultimo_descarte), str(hud.ultimo_descarte))
    hud.cerrar()


def test_compuesto_hud_contradice_api() -> None:
    print("[compuesto: HUD contradice API]")
    hud = HudFalsa("hud_ocr", t_hud=1700.0)  # 70% lejos del API
    api = FuenteFalsa("en_vivo", {"t": 1000.0, "fuente": "en_vivo", "yo": {}})
    c = FuenteCompuesta([hud, api])
    estado = c.estado()
    check("se usa API", estado.get("fuente") == "en_vivo", str(estado))
    check("historial menciona descarte HUD", any("HUD" in x and "API" in x for x in c.historial_decisiones),
          str(c.historial_decisiones))
    c.cerrar()


def test_compuesto_hud_coincide() -> None:
    print("[compuesto: HUD coincide con API]")
    hud = HudFalsa("hud_ocr", t_hud=1050.0)
    api = FuenteFalsa("en_vivo", {"t": 1000.0, "fuente": "en_vivo", "yo": {}})
    c = FuenteCompuesta([hud, api])
    estado = c.estado()
    # HUD va primero y coincide: puede ganar HUD (regla 1 + validación OK).
    check("HUD o resultado válido", isinstance(estado, dict) and estado.get("fuente") in ("hud", "en_vivo"),
          str(estado))
    check("historial existe", len(c.historial_decisiones) > 0, str(c.historial_decisiones))
    c.cerrar()


def main() -> int:
    print("test_fuentes")
    test_base()
    test_simulador()
    test_compuesto_gana_primera()
    test_compuesto_esperando()
    test_compuesto_excepcion_no_tumba()
    test_hud_validacion_coincide()
    test_hud_validacion_difiere_70()
    test_hud_real_con_estado_controlado()
    test_compuesto_hud_contradice_api()
    test_compuesto_hud_coincide()
    print()
    if fallos:
        print(f"{len(fallos)} FALLAS: {fallos}")
        return len(fallos)
    print("todo bien")
    return 0


def test_suite():
    """Entrada para pytest -q."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())

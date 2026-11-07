"""Fuente compuesta: elige la mejor lectura disponible sin inventar datos.

Reglas del proyecto:
1. La primera fuente que devuelve un estado válido gana.
2. Si el HUD contradice al API en más de 30% de reloj, se descarta el HUD
   y se usa el API.
3. Si no hay ninguna, devuelve un estado honesto de espera.
4. Registra el historial de decisiones para depuración.
"""
from __future__ import annotations

from typing import Any, Callable


def _es_hud(fuente: Any) -> bool:
    nombre = str(getattr(fuente, "nombre", "")).lower()
    return "hud" in nombre or hasattr(fuente, "validar_contra")


def _es_api(fuente: Any) -> bool:
    nombre = str(getattr(fuente, "nombre", "")).lower()
    return "vivo" in nombre or "api" in nombre or "broadcast" in nombre


def _valido(estado: Any) -> bool:
    return isinstance(estado, dict) and len(estado) > 0


class FuenteCompuesta:
    """Combina varias fuentes aplicando la política de precedencia del coach."""

    nombre = "compuesta"

    def __init__(self, fuentes: list[Any]):
        self.fuentes = list(fuentes or [])
        self.historial_decisiones: list[str] = []
        self.ultimo_error: str | None = None
        self._callbacks: list[Callable[[dict[str, Any]], None]] = []

    def _registrar(self, mensaje: str) -> None:
        self.historial_decisiones.append(mensaje)

    def disponible(self) -> bool:
        for fuente in self.fuentes:
            try:
                if fuente.disponible():
                    return True
            except Exception:
                continue
        return False

    def _leer(self, fuente: Any) -> dict[str, Any] | None:
        try:
            return fuente.estado()
        except Exception as exc:  # noqa: BLE001
            nombre = getattr(fuente, "nombre", type(fuente).__name__)
            self._registrar(f"{nombre}: excepción ignorada ({type(exc).__name__}: {exc})")
            return None

    def _estado_api(self) -> dict[str, Any] | None:
        for fuente in self.fuentes:
            if not _es_api(fuente):
                continue
            estado = self._leer(fuente)
            if _valido(estado):
                return estado
        return None

    def estado(self) -> dict[str, Any]:
        self.ultimo_error = None
        candidatos: list[tuple[Any, dict[str, Any]]] = []
        errores: list[str] = []
        for fuente in self.fuentes:
            estado = self._leer(fuente)
            if _valido(estado):
                candidatos.append((fuente, estado))
            else:
                nombre = getattr(fuente, "nombre", type(fuente).__name__)
                motivo = getattr(fuente, "ultimo_error", None)
                if motivo:
                    errores.append(f"{nombre}: {motivo}")

        if not candidatos:
            mensaje = "sin fuentes disponibles con datos válidos"
            if errores:
                mensaje += " (" + "; ".join(errores) + ")"
            self._registrar(f"esperando: {mensaje}")
            return {"listo": False, "mensaje": mensaje, "fuente": "esperando"}

        ganador_fuente, ganador_estado = candidatos[0]
        if _es_hud(ganador_fuente):
            estado_api = self._estado_api()
            if estado_api is not None:
                validador = getattr(ganador_fuente, "validar_contra", None)
                if callable(validador):
                    try:
                        coincide = bool(validador(estado_api, tolerancia=0.30))
                    except Exception as exc:  # noqa: BLE001
                        coincide = False
                        self._registrar(
                            f"HUD: validación falló ({type(exc).__name__}), se usa API"
                        )
                    if not coincide:
                        motivo = getattr(ganador_fuente, "ultimo_descarte", None)
                        self._registrar(
                            "HUD contradice API (>30% reloj): se descarta HUD y se usa API"
                            + (f" — {motivo}" if motivo else "")
                        )
                        # Busca el primer candidato API; si no, usa el estado_api leído.
                        for fuente, estado in candidatos:
                            if _es_api(fuente):
                                ganador_fuente, ganador_estado = fuente, estado
                                break
                        else:
                            # estado_api vino de una lectura directa.
                            api_candidata = next(
                                (f for f in self.fuentes if _es_api(f)), None
                            )
                            ganador_fuente = api_candidata or ganador_fuente
                            ganador_estado = estado_api
                    else:
                        self._registrar("HUD validado contra API (<=30% reloj): gana HUD")
                else:
                    self._registrar("HUD sin validador: gana HUD por precedencia")
            else:
                self._registrar("HUD gana: no hay API para contrastar")
        else:
            nombre = getattr(ganador_fuente, "nombre", type(ganador_fuente).__name__)
            self._registrar(f"gana {nombre}: primera fuente con estado válido")

        for fn in list(self._callbacks):
            try:
                fn(ganador_estado)
            except Exception:
                pass
        return ganador_estado

    def suscribir(self, fn: Callable[[dict[str, Any]], None]) -> None:
        if callable(fn):
            self._callbacks.append(fn)

    def cerrar(self) -> None:
        for fuente in self.fuentes:
            try:
                fuente.cerrar()
            except Exception:
                pass
        self._callbacks.clear()

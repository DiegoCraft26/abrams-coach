"""Interfaz explícita para fuentes de datos del coach.

El motor consume dicts crudos; las fuentes encapsulan de dónde salen esos dicts
(simulación, broadcast de Valve, OCR del HUD) detrás de un contrato común.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


class FuenteError(Exception):
    """Error genérico de una fuente de datos."""


class EstadoVacio(FuenteError):
    """La fuente no pudo producir un estado utilizable."""


@runtime_checkable
class FuenteDatos(Protocol):
    """Contrato mínimo que debe cumplir cualquier fuente."""

    nombre: str

    def disponible(self) -> bool:
        """Indica si la fuente puede intentar producir datos ahora."""
        ...

    def estado(self) -> dict[str, Any] | None:
        """Devuelve un dict crudo listo para Motor.analizar_dict, o None."""
        ...

    def suscribir(self, fn: Callable[[dict[str, Any]], None]) -> None:
        """Registra un callback para nuevos estados. Puede ser no-op."""
        ...

    def cerrar(self) -> None:
        """Libera recursos (hilos, conexiones, archivos temporales)."""
        ...

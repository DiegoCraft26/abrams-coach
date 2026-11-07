"""Bus de estado en memoria con suscriptores, thread-safe, sin dependencias."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional


class Bus:
    """Bus simple de estado.

    - ``publicar`` guarda el estado y notifica a los suscriptores.
    - ``leer`` / ``encuesta`` leen bajo lock.
    - Un suscriptor que falla no rompe a los demás; se cuenta en ``fallos``.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._estado: Any = {}
        self._version: int = 0
        self._ts: float = 0.0
        self._suscriptores: list[Callable[[Any], None]] = []
        self.fallos: int = 0

    def publicar(self, estado: Any) -> int:
        with self._lock:
            self._estado = estado
            self._version += 1
            self._ts = time.time()
            version = self._version
            suscriptores = list(self._suscriptores)
        # Notificamos fuera del lock para evitar deadlocks si un suscriptor
        # vuelve a tocar el bus.
        for fn in suscriptores:
            try:
                fn(estado)
            except Exception:
                with self._lock:
                    self.fallos += 1
        return version

    def leer(self) -> tuple[Any, int]:
        with self._lock:
            return self._estado, self._version

    def encuesta(self) -> tuple[Any, int, Optional[float]]:
        with self._lock:
            edad = (time.time() - self._ts) if self._ts else None
            return self._estado, self._version, edad

    def suscribir(self, fn: Callable[[Any], None]) -> Callable[[], None]:
        with self._lock:
            self._suscriptores.append(fn)

        def desuscribir() -> None:
            with self._lock:
                try:
                    self._suscriptores.remove(fn)
                except ValueError:
                    pass

        return desuscribir

    def version(self) -> int:
        with self._lock:
            return self._version

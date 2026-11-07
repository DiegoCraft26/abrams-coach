"""Presupuesto de llamadas LLM: ventana por minuto, techo por sesión y caché.

Todo thread-safe: el panel sirve con hilos, así que cada acceso lleva lock.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class Presupuesto:
    """Controla cuánto puede gastar el agente antes de dejar de llamar."""

    def __init__(self, llamadas_min: int = 6, llamadas_sesion: int = 120,
                 cache_s: float = 300, max_tokens: int = 800):
        self.llamadas_min = llamadas_min
        self.llamadas_sesion = llamadas_sesion
        self.cache_s = cache_s
        self.max_tokens = max_tokens
        self._lock = threading.Lock()
        self._marca_minuto: deque[float] = deque()
        self._llamadas = 0
        self._tokens = 0
        self._desde = time.time()
        self._cache: dict[str, tuple[float, object]] = {}

    def _limpiar_minuto(self) -> None:
        ahora = time.time()
        while self._marca_minuto and ahora - self._marca_minuto[0] >= 60:
            self._marca_minuto.popleft()

    def puede_llamar(self) -> bool:
        """True si quedan llamadas en la ventana de 60 s y en la sesión."""
        with self._lock:
            self._limpiar_minuto()
            return (len(self._marca_minuto) < self.llamadas_min
                    and self._llamadas < self.llamadas_sesion)

    def registrar(self, tokens: int | None) -> None:
        """Registra una llamada ya hecha y sus tokens (si se conocen)."""
        with self._lock:
            self._llamadas += 1
            self._marca_minuto.append(time.time())
            if tokens:
                self._tokens += int(tokens)

    @property
    def gastado(self) -> dict:
        """Dict con llamadas, tokens y desde cuándo lleva la sesión."""
        with self._lock:
            return {"llamadas": self._llamadas, "tokens": self._tokens,
                    "desde": self._desde}

    def cache(self, clave: str):
        """Devuelve el valor guardado si no expiró; None si no existe o expiró."""
        with self._lock:
            entrada = self._cache.get(clave)
            if entrada is None:
                return None
            guardado, valor = entrada
            if time.time() - guardado > self.cache_s:
                del self._cache[clave]
                return None
            return valor

    def guardar_cache(self, clave: str, valor) -> None:
        """Guarda `valor` bajo `clave` durante `cache_s` segundos."""
        with self._lock:
            self._cache[clave] = (time.time(), valor)

    def estado(self) -> dict:
        """Resumen legible para la UI (sin secretos ni detalles internos)."""
        with self._lock:
            self._limpiar_minuto()
            return {
                "llamadas_minuto": len(self._marca_minuto),
                "limite_minuto": self.llamadas_min,
                "llamadas_sesion": self._llamadas,
                "limite_sesion": self.llamadas_sesion,
                "tokens": self._tokens,
                "max_tokens": self.max_tokens,
                "puede_llamar": (len(self._marca_minuto) < self.llamadas_min
                                 and self._llamadas < self.llamadas_sesion),
            }

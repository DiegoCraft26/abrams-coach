"""Fuente HUD por OCR: reloj y oro leídos de la pantalla.

Es rápida pero frágil; su resultado debe contrastarse con la API cuando exista.
"""
from __future__ import annotations

import subprocess
from typing import Any, Callable


class FuenteHud:
    """Envuelve coach.hud.leer_hud() con validación honesta."""

    def __init__(self, nombre: str = "hud_ocr"):
        self.nombre = nombre
        self.ultimo_error: str | None = None
        self.ultimo_descarte: str | None = None
        self._callbacks: list[Callable[[dict[str, Any]], None]] = []

    def disponible(self) -> bool:
        try:
            from coach import hud

            datos = hud.leer_hud()
            return datos is not None
        except (subprocess.SubprocessError, OSError):
            self.ultimo_error = "no se pudo capturar la pantalla"
            return False
        except Exception as exc:  # noqa: BLE001
            self.ultimo_error = f"{type(exc).__name__}: {exc}"
            return False

    def estado(self) -> dict[str, Any] | None:
        try:
            from coach import hud

            datos = hud.leer_hud()
        except (subprocess.SubprocessError, OSError) as exc:
            self.ultimo_error = f"{type(exc).__name__}: {exc}"
            return None
        except Exception as exc:  # noqa: BLE001
            self.ultimo_error = f"{type(exc).__name__}: {exc}"
            return None
        if datos is None:
            self.ultimo_error = "HUD sin lectura"
            return None
        estado = {
            "t": datos.get("t"),
            "oro": datos.get("oro"),
            "fuente": "hud",
            "notas": ["HUD OCR: reloj y oro de tu pantalla"],
        }
        self.ultimo_error = None
        for fn in list(self._callbacks):
            try:
                fn(estado)
            except Exception:
                pass
        return estado

    def validar_contra(self, estado_api: dict[str, Any] | None, tolerancia: float = 0.30) -> bool:
        """Compara el reloj del HUD con el del API.

        Devuelve True solo si la diferencia relativa es <= tolerancia. Si difiere
        más, descarta el estado y anota el motivo en ultimo_descarte.
        """
        try:
            hud_estado = self.estado()
        except Exception as exc:  # noqa: BLE001
            self.ultimo_descarte = f"HUD ilegible: {type(exc).__name__}: {exc}"
            return False
        if hud_estado is None:
            self.ultimo_descarte = self.ultimo_error or "HUD sin estado"
            return False
        if not isinstance(estado_api, dict):
            self.ultimo_descarte = "sin estado de API para comparar"
            return False
        t_hud = hud_estado.get("t")
        t_api = estado_api.get("t")
        if t_hud is None or t_api is None:
            self.ultimo_descarte = "reloj HUD o API ausente"
            return False
        try:
            hud_n = float(t_hud)
            api_n = float(t_api)
        except (TypeError, ValueError):
            self.ultimo_descarte = "reloj HUD o API no numérico"
            return False
        referencia = max(abs(api_n), 1.0)
        diferencia = abs(hud_n - api_n)
        relativa = diferencia / referencia
        if relativa > float(tolerancia):
            self.ultimo_descarte = (
                f"HUD descartado: reloj {hud_n:g}s vs API {api_n:g}s "
                f"(diferencia relativa {relativa:.0%} > {float(tolerancia):.0%})"
            )
            return False
        self.ultimo_descarte = None
        return True

    def suscribir(self, fn: Callable[[dict[str, Any]], None]) -> None:
        if callable(fn):
            self._callbacks.append(fn)

    def cerrar(self) -> None:
        self._callbacks.clear()

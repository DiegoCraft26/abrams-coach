"""Fuente simulada que reproduce el demo actual sin red ni juego abierto.

Cada instancia mantiene su propio reloj y no comparte estado global con otras.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable


def _ruta_conocimiento() -> str:
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(raiz, "data", "conocimiento.json")


class FuenteSimulador:
    """Genera estados plausibles de Abrams para probar el motor y la UI."""

    nombre = "simulador"

    def __init__(self, t_inicial: float = 900.0, acelerar: float = 30.0):
        self.t = float(t_inicial)
        self.acelerar = float(acelerar)
        self._callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._items_por_lift: list[str] = []
        self._cargar_conocimiento()

    def _cargar_conocimiento(self) -> None:
        try:
            with open(_ruta_conocimiento(), encoding="utf-8") as f:
                conoc = json.load(f)
        except Exception:
            conoc = {}
        items = conoc.get("items", {}) if isinstance(conoc, dict) else {}
        # Ítems asequibles/plausibles ordenados por lift residual, como el demo.
        disponibles = []
        for iid, datos in items.items():
            if not isinstance(datos, dict):
                continue
            costo = datos.get("costo")
            if (costo or 0) <= 1600:
                lift = datos.get("lift_residual")
                try:
                    lift_n = float(lift) if lift is not None else 0.0
                except (TypeError, ValueError):
                    lift_n = 0.0
                disponibles.append((str(iid), lift_n))
        disponibles.sort(key=lambda x: -x[1])
        self._items_por_lift = [iid for iid, _ in disponibles]

    def _inventario(self, t: float) -> list[str]:
        if not self._items_por_lift:
            # Respaldo determinista si falta conocimiento.json.
            base = ["800", "1548066885", "1437614329", "7409189", "26002154", "98582110"]
            return base[:2] if t < 600 else base[:4] if t < 1200 else base[:6]
        if t < 600:
            return self._items_por_lift[:2]
        if t < 1200:
            return self._items_por_lift[:4]
        return self._items_por_lift[:6]

    def disponible(self) -> bool:
        return True

    def estado(self) -> dict[str, Any] | None:
        t = self.t
        progreso = max(0.0, min(t / 2400.0, 1.0))
        almas = int(300 + progreso * 12000)
        enemigos = [
            {"heroe": h, "almas": int(almas * factor)}
            for h, factor in [
                ("haze", 0.85),
                ("lash", 0.90),
                ("seven", 0.95),
                ("bebop", 1.00),
                ("wraith", 1.05),
            ]
        ]
        datos = {
            "t": t,
            "yo": {"heroe": "Abrams", "almas": almas, "items": self._inventario(t)},
            "aliados": [
                {"heroe": "kelvin", "almas": int(almas * 0.9)},
                {"heroe": "dynamo", "almas": int(almas * 0.8)},
            ],
            "enemigos": enemigos,
            "confianza": 0.9,
            "fuente": "simulado",
        }
        if self.acelerar:
            self.t = min(self.t + 20.0 * self.acelerar, 2399.0)
            if self.t >= 2399.0:
                self.t = 0.0
        for fn in list(self._callbacks):
            try:
                fn(datos)
            except Exception:
                pass
        return datos

    def suscribir(self, fn: Callable[[dict[str, Any]], None]) -> None:
        if callable(fn):
            self._callbacks.append(fn)

    def cerrar(self) -> None:
        self._callbacks.clear()

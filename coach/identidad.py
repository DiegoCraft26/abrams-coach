"""Quiénes somos cuando le pedimos algo a un servidor ajeno.

Una sola cadena para todas las peticiones salientes. El 2026-11-18 la app mandaba
seis variantes distintas —«abrams-coach/1.0 (HUD remoto)», «(analitica con
presupuesto)», «(assets de ítems)», «(nombres de héroes)»— y una ruta, el watcher
del live en `ui/app.py`, iba sin cabecera y salía como `Python-urllib/3.x`.

Para quien mira sus registros eso no es una aplicación: son siete clientes, uno
anónimo. Y una aplicación que no se puede identificar en los registros del que te
presta la API no tiene forma de pedir nada ni de defenderse de un bloqueo.

El paréntesis con el repo es a propósito: es un contacto. Quien vea tráfico raro
tiene a dónde escribir antes de banear.
"""
from __future__ import annotations

APLICACION = "abrams-coach"
VERSION = "1.0"
REPO = "https://github.com/DiegoCraft26/abrams-coach"

# Formato: aplicacion/version (+contacto)
AGENTE = f"{APLICACION}/{VERSION} (+{REPO})"


def cabeceras(**extra: str) -> dict[str, str]:
    """Cabeceras base para una petición saliente, con lo que se quiera añadir."""
    base = {"User-Agent": AGENTE}
    base.update(extra)
    return base

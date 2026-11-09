"""Telemetría de las decisiones de identidad: qué partida se creyó y por qué.

El relevo pedía «telemetría de cada decisión (id leído, validado, motivo de rechazo)».
Sin eso, cuando el panel enseña una partida que no es, no hay forma de saber si el fallo
fue del HUD, de la cuenta o del listado: se discute de memoria.

Cada línea es un JSON con hora, evento y campos. Se guarda en `salida/telemetria.jsonl`
(ignorado por git) y se recorta sola: es un registro de depuración, no un archivo eterno.
"""
from __future__ import annotations

import json
import os
import threading
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA = os.path.join(RAIZ, "salida", "telemetria.jsonl")
MAX_LINEAS = 4000          # al pasarse, se deja la mitad más reciente
_LOCK = threading.Lock()


def anotar(evento: str, ruta: str | None = None, **campos):
    """Apunte una decisión. Nunca lanza: la telemetría no puede tumbar el bucle."""
    destino = ruta or RUTA
    linea = {"ts": round(time.time(), 3), "evento": str(evento)[:40]}
    for clave, valor in campos.items():
        if isinstance(valor, (str, int, float, bool)) or valor is None:
            linea[clave] = valor
        else:
            linea[clave] = str(valor)[:200]
    with _LOCK:
        try:
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            with open(destino, "a", encoding="utf-8") as f:
                f.write(json.dumps(linea, ensure_ascii=False) + "\n")
            _recortar(destino)
        except OSError:
            pass
    return linea


def _recortar(destino: str):
    try:
        if os.path.getsize(destino) < 400_000:
            return
        with open(destino, encoding="utf-8") as f:
            lineas = f.readlines()
        if len(lineas) <= MAX_LINEAS:
            return
        with open(destino, "w", encoding="utf-8") as f:
            f.writelines(lineas[-MAX_LINEAS // 2:])
    except OSError:
        pass


def leer(ultimos: int = 20, ruta: str | None = None) -> list[dict]:
    """Las últimas decisiones, de la más vieja a la más nueva."""
    destino = ruta or RUTA
    try:
        with open(destino, encoding="utf-8") as f:
            lineas = f.readlines()[-max(1, int(ultimos)):]
    except OSError:
        return []
    salida = []
    for linea in lineas:
        try:
            salida.append(json.loads(linea))
        except json.JSONDecodeError:
            continue
    return salida


def resumen(ruta: str | None = None) -> dict:
    """Cuántas veces se creyó una partida, por vía, y cuántas veces hubo rechazo.

    Es lo que hay que mirar tras una partida para saber si la identidad está sana.
    """
    eventos = leer(4000, ruta)
    vias: dict[str, int] = {}
    rechazos = 0
    for linea in eventos:
        via = linea.get("via")
        if via:
            vias[str(via)] = vias.get(str(via), 0) + 1
        if linea.get("rechazo"):
            rechazos += 1
    return {"eventos": len(eventos), "por_via": vias, "rechazos": rechazos,
            "ultimo": eventos[-1] if eventos else None}

"""Datos del overlay: de `/api/estado` a lo único que se pinta. Sin GTK.

Separado de `overlay.py` para poder probarlo sin `gi`: aquí no hay ventanas, solo el
recorte del estado. El overlay (GTK) importa estas funciones.
"""
from __future__ import annotations

import json
import urllib.request

INTERVALO = 1.0


# --- datos -----------------------------------------------------------------------------
def _get(url: str, timeout: float = 1.5) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:   # noqa: S310
            return r.read()
    except Exception:                                              # noqa: BLE001
        return None


def estado(url: str) -> dict | None:
    crudo = _get(url.rstrip("/") + "/api/estado")
    if not crudo:
        return None
    try:
        return json.loads(crudo)
    except Exception:                                              # noqa: BLE001
        return None


def _num(v) -> int:
    try:
        return int(round(float(v)))
    except Exception:                                              # noqa: BLE001
        return 0


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ",")


def resumen(d: dict) -> dict:
    """Traduce /api/estado a lo único que se pinta. Sin reglas: solo recorta."""
    dec = d.get("decision") or {}
    objetivo = dec.get("objetivo") or dec.get("item") or {}
    camino = dec.get("camino") or d.get("camino") or []

    # Si la decisión no trae objetivo (estado viejo), se usa el primer ítem «ahora».
    if not objetivo:
        for it in camino:
            if it.get("estado") == "ahora":
                objetivo = it
                break
    if not objetivo and camino:
        objetivo = camino[0]

    tiles = []
    for it in camino[:6]:
        est = str(it.get("estado") or "").lower()
        clase = "hecho" if est in ("comprado", "hecho", "listo", "ok") else \
                "ahora" if est in ("ahora", "siguiente", "next") else "despues"
        tiles.append({"id": str(it.get("id") or ""), "clase": clase})

    venta = (d.get("venta") or {}).get("nombre") or ""
    accion = str(dec.get("accion") or "").upper()

    obj_sesion = (d.get("objetivo") or {}).get("texto") or ""
    return {
        "listo": d.get("listo") is not False,
        "objetivo": obj_sesion,
        "rancio": bool(d.get("rancio")),
        "edad": _num(d.get("edad_s")),
        "nombre": str(objetivo.get("nombre") or ""),
        "id": str(objetivo.get("id") or ""),
        "costo": _num(objetivo.get("costo")),
        "vende": venta if accion == "VENDER" else "",
        "tiles": tiles,
    }



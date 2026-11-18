"""Nombres de héroes al día: el archivo local se quedaba con los que existían al copiarlo.

Síntoma real del 2026-11-15: el índice histórico mostraba «86» y «88» como si fueran
nombres. Son Violet y Baba, héroes añadidos después de la última copia de
`data/heroes.json`. El panel y los informes los mostraban como números.

`combinar()` es puro y solo añade o corrige el campo `nombre`: el resto del archivo (ids,
slugs) se respeta tal cual para no romper nada que ya lo lea.
"""
from __future__ import annotations

import json
import os
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HEROES = os.path.join(RAIZ, "data", "heroes.json")
API = "https://api.deadlock-api.com/v1/assets/heroes"
CABECERAS = {"User-Agent": "abrams-coach/1.0 (nombres de héroes)",
             "Accept": "application/json"}


def combinar(local, api):
    """Devuelve el diccionario local con los nombres del API aplicados.

    No borra héroes que el API ya no liste: si alguien jugó una partida con un héroe
    retirado, el histórico la necesita para nombrarla.
    """
    salida = {str(k): dict(v) for k, v in (local or {}).items()}
    for h in api or []:
        try:
            hid = int(h["id"])
        except (KeyError, TypeError, ValueError):
            continue
        nombre = str(h.get("name") or "").strip()
        if not nombre:
            continue
        fila = salida.setdefault(str(hid), {"id": hid})
        anterior = fila.get("nombre")
        fila["nombre"] = nombre
        fila["id"] = hid
        if anterior and anterior != nombre:
            fila["nombre_anterior"] = anterior
    return salida


def _api():
    with urllib.request.urlopen(urllib.request.Request(API, headers=CABECERAS),
                                timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def actualizar(ruta=None, bajada=None):
    """Aplica los nombres del API al archivo local. Devuelve cuántos cambiaron."""
    ruta = ruta or HEROES
    with open(ruta, encoding="utf-8") as f:
        local = json.load(f)
    nuevo = combinar(local, bajada if bajada is not None else _api())
    cambios = sum(1 for k, v in nuevo.items()
                  if (local.get(k) or {}).get("nombre") != v.get("nombre"))
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(nuevo, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(temporal, ruta)
    return cambios

"""Qué es cada id de «ítem»: objeto de tienda o habilidad.

Descubierto el 2026-11-15 midiendo el camino de Abrams: los primeros «ítems» de cada
partida eran `715762406`, `2824119765`, `509856396`… que el API de assets identifica como
**habilidades** (Infernal Resilience, Shoulder Charge, Seismic Impact). El array `items`
del metadata mezcla compras de tienda con subidas de habilidad, así que ordenarlo sin
filtrar produce una «apertura» que es en realidad el orden de subida de habilidades.

Este módulo guarda el catálogo de assets del API (782 entradas) y responde `es_item(id)`.
No toca `data/catalogo.json`, que el motor usa para costes y tiers: aquí solo se añade el
tipo, para no cambiar decisiones ya validadas.
"""
from __future__ import annotations

import json
import os
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUTA = os.path.join(RAIZ, "data", "items_tipos.json")
API = "https://api.deadlock-api.com/v1/assets/items"
CABECERAS = {"User-Agent": "abrams-coach/1.0 (assets de ítems)",
             "Accept": "application/json"}

_cache = {"datos": None, "ts": 0.0}


def resumir(assets):
    """{id: {'nombre', 'tipo', 'costo'}} desde la lista del API. Puro."""
    salida = {}
    for a in assets or []:
        try:
            iid = int(a["id"])
        except (KeyError, TypeError, ValueError):
            continue
        salida[str(iid)] = {"nombre": a.get("name") or str(iid),
                            "tipo": a.get("type") or "?",
                            "costo": a.get("cost")}
    return salida


def actualizar(ruta=None, bajada=None):
    ruta = ruta or RUTA
    if bajada is None:
        with urllib.request.urlopen(urllib.request.Request(API, headers=CABECERAS),
                                    timeout=90) as r:
            bajada = json.loads(r.read().decode("utf-8"))
    datos = resumir(bajada)
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(temporal, ruta)
    return datos


def cargar(max_edad_s=86400.0):
    """El catálogo en memoria. Si no hay archivo, devuelve {} y todo pasa el filtro."""
    import time
    ahora = time.time()
    if _cache["datos"] is not None and ahora - _cache["ts"] < max_edad_s:
        return _cache["datos"]
    try:
        with open(RUTA, encoding="utf-8") as f:
            _cache["datos"] = json.load(f)
    except (OSError, ValueError):
        _cache["datos"] = {}
    _cache["ts"] = ahora
    return _cache["datos"]


#: En los assets del API, lo que se compra en la tienda es `upgrade`. `ability` son las
#: habilidades (sus subidas también viajan en el array `items` del metadata) y `weapon`
#: las armas base. Confundirlos fue el error del 2026-11-15.
TIPO_TIENDA = "upgrade"


def es_item(iid, tabla=None):
    """True si es objeto de tienda.

    Lo que no está en el catálogo **cuenta como objeto**: si un parche añade un ítem y el
    catálogo todavía no lo tiene, perderlo sería peor que contarlo. Solo se descarta lo
    que se sabe que es habilidad o arma base.
    """
    tabla = tabla if tabla is not None else cargar()
    if not tabla:
        return True
    fila = tabla.get(str(iid))
    if fila is None:
        return True
    return str(fila.get("tipo") or "").lower() == TIPO_TIENDA


def nombre(iid, tabla=None):
    tabla = tabla if tabla is not None else cargar()
    return (tabla.get(str(iid)) or {}).get("nombre")

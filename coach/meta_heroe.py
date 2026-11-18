"""Meta por héroe: del agregado de la API a una lista de apertura defendible.

El coach solo sabía construir para Abrams porque lo único con verdad de campo eran sus
626 partidas (`data/replay_cache.json`). Para los demás héroes no hay partidas propias,
así que hay que partir de los agregados públicos de `api.deadlock-api.com`... con cuidado,
porque un agregado no es un banco de partidas.

Lo que se midió el 2026-11-15 con Abrams (el único héroe con las dos cosas):

- ordenar los ítems por winrate o por popularidad **no** reproduce lo que compran los que
  ganan: Melee Lifesteal y Restorative Shot salen arriba y no están en la apertura real;
- lo que sí discrimina es **cuándo se compra** (`avg_buy_time_relative`) combinado con el
  coste: con «coste ≤ 800 y comprado antes del 27 % de la partida» aparecen los tres
  ítems de la apertura del banco (Spirit Strike, Close Quarters, Extra Regen) y solo esos
  tres de la verdad, más dos candidatos razonables.

Por eso este módulo no promete una build cerrada: entrega el **pozo temprano** de un
héroe, con su muestra y su cota de Wilson, y deja el orden y los contras al motor y al
banco. Presentar el ranking del agregado como «la build» sería inventar.
"""
from __future__ import annotations

import json
import math
import os

from .fuentes import api_analitica

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARPETA = os.path.join(RAIZ, "data", "meta")
CATALOGO = os.path.join(RAIZ, "data", "catalogo.json")

# Umbrales medidos contra la única verdad disponible (626 partidas de Abrams).
REL_MAX = 27.0          # % de la partida antes del cual se considera «apertura»
COSTO_MAX = 800         # los ítems de salida cuestan 800; no se fuerza nada más caro
MIN_MUESTRA = 2000      # por debajo de esto el winrate es ruido


def wilson(wins, losses, z=1.96):
    """Cota inferior del 95 % para un winrate con pocos datos."""
    n = wins + losses
    if n <= 0:
        return 0.0
    p = wins / n
    return (p + z * z / (2 * n)
            - z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / (1 + z * z / n)


def _catalogo(ruta=None):
    try:
        with open(ruta or CATALOGO, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def derivar(filas, catalogo=None, rel_max=REL_MAX, costo_max=COSTO_MAX, k=5,
            min_muestra=MIN_MUESTRA):
    """Pozo temprano del héroe a partir de `/v1/analytics/item-stats`.

    Devuelve {'apertura': [...], 'base_wr': x, 'muestra': n, 'criterio': {...}}.
    Cada ítem lleva id, nombre, coste, cuándo se compra y la cota inferior de winrate.
    """
    catalogo = catalogo if catalogo is not None else _catalogo()
    filas = [f for f in (filas or []) if isinstance(f, dict)]
    total_w = sum(int(f.get("wins") or 0) for f in filas)
    total_l = sum(int(f.get("losses") or 0) for f in filas)
    base = total_w / max(1, total_w + total_l)

    candidatos = []
    for f in filas:
        try:
            iid = int(f["item_id"])
            wins, losses = int(f["wins"]), int(f["losses"])
        except (KeyError, TypeError, ValueError):
            continue
        if wins + losses < min_muestra:
            continue
        info = catalogo.get(str(iid)) or {}
        costo = info.get("costo")
        if not isinstance(costo, int) or costo > costo_max:
            continue
        rel = f.get("avg_buy_time_relative")
        if not isinstance(rel, (int, float)) or rel > rel_max:
            continue
        candidatos.append({
            "id": iid,
            "nombre": info.get("nombre") or str(iid),
            "costo": costo,
            "rel_pct": round(float(rel), 1),
            "muestra": wins + losses,
            "winrate": round(wins / max(1, wins + losses), 4),
            "wlb": round(wilson(wins, losses), 4),
        })
    candidatos.sort(key=lambda c: (-c["wlb"], -c["muestra"]))
    return {
        "apertura": candidatos[:k],
        "base_wr": round(base, 4),
        "muestra": total_w + total_l,
        "criterio": {"rel_max": rel_max, "costo_max": costo_max,
                     "min_muestra": min_muestra, "orden": "wilson"},
    }


def desde_api(hero_id, forzar=False, **kw):
    """Pide los agregados del héroe (con caché y presupuesto) y deriva."""
    filas = api_analitica.pedir("/v1/analytics/item-stats", hero_id=int(hero_id),
                                min_matches=200, forzar=forzar)
    return derivar(filas, **kw)


def comparar(derivado, esperados):
    """Cuántos de los ítems esperados aparecen en el pozo, y qué sobra.

    `esperados` son ids (str o int) de la verdad de campo — para Abrams, la apertura del
    banco de 626 partidas. Un pozo con los tres acierta como conjunto; el orden no se
    juzga aquí porque el motor lo decide con el banco.
    """
    pozo = [int(c["id"]) for c in (derivado or {}).get("apertura", [])]
    esperados = [int(x) for x in (esperados or [])]
    faltan = [x for x in esperados if x not in pozo]
    return {"aciertos": len([x for x in esperados if x in pozo]),
            "de": len(esperados), "faltan": faltan,
            "sobran": [x for x in pozo if x not in esperados]}


def ruta_heroe(hero_id):
    return os.path.join(CARPETA, f"{int(hero_id)}.json")


def guardar(hero_id, derivado, extra=None):
    """Escribe `data/meta/<hero_id>.json`. Devuelve la ruta."""
    datos = dict(derivado or {})
    datos["hero_id"] = int(hero_id)
    if extra:
        datos.update(extra)
    os.makedirs(CARPETA, exist_ok=True)
    ruta = ruta_heroe(hero_id)
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    os.replace(temporal, ruta)
    return ruta


def cargar(hero_id):
    """El meta guardado del héroe, o None si no se ha generado."""
    try:
        with open(ruta_heroe(hero_id), encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None

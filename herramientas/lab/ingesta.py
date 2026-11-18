#!/usr/bin/env python3
"""Carga en `datos/lab.db` las compras ordenadas de cada partida.

Fuente de hoy: `data/replay_cache.json` (626 partidas de Abrams con línea de tiempo de
compras). El formato mezcla ítems de tienda con mejoras de habilidad, así que sólo
entran los que son `shopable` y tienen coste: las habilidades no cuestan almas y,
si se cuelan, la primera compra sale a los 15 s y todo el análisis se cae.

`--desde-api` queda para cuando haya que bajar partidas nuevas: descarga el detalle por
`match_id` con `/v1/matches/{id}` y guarda lo mismo. No se ejecuta sin pedirlo porque
una tanda de partidas son miles de peticiones.

Uso:
    python3 herramientas/lab/ingesta.py
    python3 herramientas/lab/ingesta.py --replays otra_ruta.json --heroe Abrams
"""
from __future__ import annotations

import argparse
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from herramientas.lab import db  # noqa: E402

REPLAYS = os.path.join(RAIZ, "data", "replay_cache.json")
ITEMS = os.path.join(RAIZ, "data", "items.json")


def cargar_items():
    with open(ITEMS, encoding="utf-8") as f:
        datos = json.load(f)
    valores = datos.values() if isinstance(datos, dict) else datos
    return {str(v.get("id")): v for v in valores}


def compras_de(match, items):
    """[(t, id, coste, vendido_t)] sólo de ítems comprables, ordenado por tiempo."""
    crudo = ((match.get("yo") or {}).get("items") or [])
    filas = []
    for x in crudo:
        iid = str(x.get("id"))
        info = items.get(iid)
        if not info or not info.get("shopable") or not (info.get("cost") or 0):
            continue
        filas.append((float(x.get("t") or 0), iid, info.get("cost") or 0,
                      x.get("vendido")))
    filas.sort(key=lambda f: f[0])
    return filas


def main():
    ap = argparse.ArgumentParser(description="Ingesta de compras al laboratorio")
    ap.add_argument("--replays", default=REPLAYS)
    ap.add_argument("--heroe", default="Abrams")
    ap.add_argument("--db", default=db.RUTA)
    args = ap.parse_args()

    with open(args.replays, encoding="utf-8") as f:
        partidas = json.load(f)
    items = cargar_items()

    con = db.conectar(args.db)
    db.crear_esquema(con)
    guardadas = compras = 0
    for m in partidas:
        mid = m.get("match_id")
        if not mid:
            continue
        filas = compras_de(m, items)
        if len(filas) < 3:                 # sin línea de compras no aporta nada
            continue
        db.guardar_partida(con, mid, args.heroe, gane=m.get("gane"),
                           duracion_s=m.get("duracion_s"),
                           fuente=os.path.basename(args.replays))
        db.guardar_compras(con, mid, filas)
        guardadas += 1
        compras += len(filas)
    con.commit()

    r = db.resumen(con)
    print(f"partidas {guardadas} · compras {compras} · base {args.db}")
    print(f"acumulado: {r['partidas']} partidas, {r['compras']} compras, "
          f"{r['ensayos']} ensayos · héroes {r['heroes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

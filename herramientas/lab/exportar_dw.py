#!/usr/bin/env python3
"""Exporta el ΔW por ítem (partidas reales del parche) para que el motor lo use.

El motor venía puntuando candidatos por frecuencia del grafo + economía + balance. La
frecuencia dice «qué se compra mucho», no «qué gana». Este export deja en
`data/dw_items.json` el ΔW medido sobre 20 500 partidas (minuto × net worth), que es lo
que `_elegir` puede usar como término extra de puntuación.

Uso:
    python3 herramientas/lab/exportar_dw.py
    python3 herramientas/lab/exportar_dw.py --min-n 300 --salida data/dw_items.json
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from herramientas.lab import db  # noqa: E402

SALIDA = os.path.join(RAIZ, "data", "dw_items.json")


def main():
    ap = argparse.ArgumentParser(description="Exporta ΔW por ítem")
    ap.add_argument("--db", default=db.RUTA)
    ap.add_argument("--heroe", type=int, default=6)
    ap.add_argument("--min-n", type=int, default=300)
    ap.add_argument("--salida", default=SALIDA)
    args = ap.parse_args()

    con = db.conectar(args.db)
    filas = [dict(r) for r in con.execute("""
        SELECT c.t, c.item_id, c.net_worth, j.ganador
          FROM compras_api c
          JOIN jugadores_api j
            ON j.match_id = c.match_id AND j.player_slot = c.player_slot
         WHERE j.hero_id = ? AND c.coste > 0
    """, (args.heroe,))]
    if not filas:
        print("sin datos: corre ingesta_api.py")
        return 1

    glob = sum(f["ganador"] for f in filas) / len(filas)
    celdas = collections.defaultdict(lambda: [0, 0])
    for f in filas:
        k = (min(int(f["t"] // 360), 5), min(int(f["net_worth"] // 6000), 6))
        celdas[k][0] += f["ganador"]
        celdas[k][1] += 1
    P = {k: (v[0] + 20 * glob) / (v[1] + 20) for k, v in celdas.items()}
    por = collections.defaultdict(list)
    for f in filas:
        k = (min(int(f["t"] // 360), 5), min(int(f["net_worth"] // 6000), 6))
        por[f["item_id"]].append(f["ganador"] - P[k])

    items = {}
    for iid, v in por.items():
        if len(v) < args.min_n:
            continue
        items[str(iid)] = {"dw": round(sum(v) / len(v), 5), "n": len(v)}

    # Normaliza a [-1, 1] para que el término entre en la misma escala que frecuencia.
    if items:
        valores = [x["dw"] for x in items.values()]
        lo, hi = min(valores), max(valores)
        rango = (hi - lo) or 1.0
        for x in items.values():
            x["norm"] = round((x["dw"] - lo) / rango * 2 - 1, 4)

    datos = {"generado": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "fuente": os.path.relpath(args.db, RAIZ),
             "heroe": args.heroe, "min_n": args.min_n,
             "wr_base": round(glob, 4), "items": items}
    with open(args.salida, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    print(f"{len(items)} ítems → {os.path.relpath(args.salida, RAIZ)} "
          f"(n≥{args.min_n}, base {glob:.1%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

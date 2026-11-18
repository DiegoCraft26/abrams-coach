#!/usr/bin/env python3
"""Amplía el pool de candidates con partidas RANKEADAS de Abrams de la temporada 2.

Por qué: muestrear al azar entre las cuentas de la caché da ~22 % de cuentas con partidas
de rango (el resto juega solo unranked), y sin rango no hay serie de badge que medir.
`/v1/matches/metadata` acepta `match_mode=ranked` y `hero_ids=6`, así que una petición de
1000 partidas devuelve 1000 filas de jugadores de Abrams que sí juegan rankeado.

Escribe en `datos/macro/cache/meta_extra/` (no toca `data/api_cache/`, que es de solo
lectura). Reanudable por cursor de `match_id`, con el mismo tope de 150 req/min.

Uso:
    python3 herramientas/macro/pool_rankeado.py --lotes 6
"""
from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import BASE, Freno, Presupuesto, escribir_json, traer  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATOS = os.path.join(RAIZ, "datos", "macro")
SALIDA = os.path.join(DATOS, "cache", "meta_extra")
CURSOR = os.path.join(DATOS, "cache", "meta_extra_cursor.json")
PRESUPUESTO = os.path.join(DATOS, "presupuesto.json")
TEMPORADA_2 = 1793908800


def main():
    ap = argparse.ArgumentParser(description="Pool de cuentas rankeadas de Abrams")
    ap.add_argument("--lotes", type=int, default=6, help="peticiones de 1000 partidas")
    ap.add_argument("--desde", type=int, default=TEMPORADA_2,
                    help="min_unix_timestamp (default: inicio de temporada 2)")
    ap.add_argument("--reiniciar", action="store_true",
                    help="ignora el cursor guardado (para muestrear otro tramo)")
    args = ap.parse_args()

    os.makedirs(SALIDA, exist_ok=True)
    pres = Presupuesto(PRESUPUESTO)
    cursor = 0
    if not args.reiniciar:
        try:
            with open(CURSOR, encoding="utf-8") as f:
                cursor = int(f.read().strip() or 0)
        except (OSError, ValueError):
            pass

    for lote in range(args.lotes):
        q = {"match_mode": "ranked", "hero_ids": "6", "limit": "1000",
             "min_unix_timestamp": str(args.desde), "format": "json",
             "order_by": "match_id", "order_direction": "asc",
             # sin esto la respuesta no trae `players` y no hay account_id que sacar
             "include_player_info": "true"}
        if cursor:
            q["min_match_id"] = str(cursor)
        url = f"{BASE}/v1/matches/metadata?{urlencode(q)}"
        try:
            datos = traer(pres, url)
        except Freno as e:
            print(f"FRENO: {e}", file=sys.stderr)
            sys.exit(3)
        if not isinstance(datos, list) or not datos:
            print(f"lote {lote + 1}: sin datos ({type(datos).__name__})", flush=True)
            break
        con_jugadores = sum(1 for m in datos if m.get("players"))
        if not con_jugadores:
            print("la respuesta no trae `players`: no sirve de semilla", file=sys.stderr)
            sys.exit(4)
        ids = [m.get("match_id") or 0 for m in datos]
        cursor = max(ids)
        ruta = os.path.join(SALIDA, f"lote_{cursor:012d}.json")
        escribir_json(ruta, datos)
        with open(CURSOR, "w", encoding="utf-8") as f:
            f.write(str(cursor))
        ganadas = sum(1 for m in datos if (m.get("average_badge") or 0) > 0)
        print(f"lote {lote + 1}: {len(datos)} partidas (cursor {cursor}) · "
              f"{ganadas} con badge · {os.path.basename(ruta)}", flush=True)
        if len(datos) < 1000:
            break
    print(f"escrito en {SALIDA}")


if __name__ == "__main__":
    main()

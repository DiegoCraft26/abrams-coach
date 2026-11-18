#!/usr/bin/env python3
"""Mide duplas con `/v1/players/{account_id}/mate-stats?same_party=true`.

Por qué: `match-history` no trae tamaño de party, así que la única vía barata de ver si
los que suben juegan acompañados es el endpoint de compañeros filtrado por `same_party`
(solo gente con la que compartió party, no rivales ni aleatorios).

Guarda un resumen por cuenta (mate_id, partidas juntas, victorias) en
`datos/macro/cache/mates/{account_id}.json`; reanudable y con el mismo tope de 150 req/min.

Uso:
    python3 herramientas/macro/duplas.py
"""
from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (BASE, Freno, Presupuesto, escribir_json, leer_json,  # noqa: E402
                    traer)

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATOS = os.path.join(RAIZ, "datos", "macro")
SALIDA = os.path.join(DATOS, "cache", "mates")
PRESUPUESTO = os.path.join(DATOS, "presupuesto.json")
TEMPORADA_2 = 1793908800


def main():
    ap = argparse.ArgumentParser(description="Duplas por cuenta (mate-stats)")
    ap.add_argument("--minimo-partidas", type=int, default=1)
    ap.add_argument("--minimo-rankeds", type=int, default=0,
                    help="si >0, solo cuentas con esa cantidad de partidas rankeadas en S2")
    args = ap.parse_args()

    semilla = leer_json(os.path.join(DATOS, "semilla.json"), {}) or {}
    cuentas = [int(x["account_id"]) for x in semilla.get("muestra", [])]
    if args.minimo_rankeds:
        validas = []
        for acc in cuentas:
            ruta = os.path.join(DATOS, "cache", "historial", f"{acc}.json")
            if not os.path.exists(ruta):
                continue
            filas = leer_json(ruta, []) or []
            n = sum(1 for f in filas if (f.get("start_time") or 0) >= TEMPORADA_2
                    and ((f.get("ranked_display_badge") or 0) > 0
                         or f.get("ranked_delta") is not None))
            if n >= args.minimo_rankeds:
                validas.append(acc)
        cuentas = validas
    os.makedirs(SALIDA, exist_ok=True)
    pres = Presupuesto(PRESUPUESTO)
    pendientes = [a for a in cuentas if not os.path.exists(os.path.join(SALIDA, f"{a}.json"))]
    print(f"pendientes: {len(pendientes)}/{len(cuentas)}", flush=True)

    for i, acc in enumerate(pendientes, 1):
        q = {"same_party": "true", "min_unix_timestamp": str(TEMPORADA_2),
             "min_matches_played": str(args.minimo_partidas)}
        url = f"{BASE}/v1/players/{acc}/mate-stats?{urlencode(q)}"
        try:
            datos = traer(pres, url)
        except Freno as e:
            print(f"FRENO: {e}", file=sys.stderr)
            sys.exit(3)
        except RuntimeError as e:
            print(f"  fallo {acc}: {e}", file=sys.stderr)
            continue
        resumen = [{"mate_id": m.get("mate_id"), "matches_played": m.get("matches_played"),
                    "wins": m.get("wins")}
                   for m in (datos or []) if isinstance(m, dict)]
        escribir_json(os.path.join(SALIDA, f"{acc}.json"), resumen)
        if i % 25 == 0 or i == len(pendientes):
            print(f"  {i}/{len(pendientes)} · {acc} · {len(resumen)} compañeros", flush=True)
    print(f"peticiones: {pres.total}")


if __name__ == "__main__":
    main()

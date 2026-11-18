#!/usr/bin/env python3
"""Repara lotes que la API rechazó (504) bajándolos en trozos más pequeños.

Reusa `ingesta_parches` para no duplicar la regla de parches ni el parseo. Calcula qué
match_ids del plan faltan en historico.db y los pide en trozos de --trozo (200 por
defecto; el lote de 1 000 contra partidas de 2025 devolvía 504).

Uso: python3 herramientas/lab/ingesta_parches_reparar.py [--trozo 200]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import sqlite3
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from herramientas.lab import ingesta_parches as ip  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trozo", type=int, default=200)
    args = ap.parse_args()
    os.makedirs(ip.LOTES, exist_ok=True)

    pl, meta = ip.plan(ip.parches(), 500, 500, 10000, "desc")
    feed = {p["titulo"]: (dt.datetime.fromtimestamp(p["pub"], dt.timezone.utc)
                          .strftime("%Y-%m-%d") if p.get("pub") else None)
            for p in meta["parches"]}
    etiqueta = {}
    todos = []
    for trozo in pl:
        for mid in trozo["ids"]:
            etiqueta[int(mid)] = (trozo["parche"], feed.get(trozo["parche"]),
                                  trozo["st"].get(int(mid), 0))
            todos.append(int(mid))

    con = sqlite3.connect(ip.DB)
    con.executescript(ip.ESQUEMA)
    tengo = {r[0] for r in con.execute("SELECT match_id FROM partidas")}
    falta = [m for m in todos if m not in tengo]
    print("plan %d · en db %d · faltan %d" % (len(todos), len(todos) - len(falta), len(falta)))
    if not falta:
        return 0
    coste = ip.costes()
    pausa = os.path.join(ip.PARCHES, "pausa.json")
    trozos = [falta[i:i + args.trozo] for i in range(0, len(falta), args.trozo)]
    for k, ids in enumerate(trozos, 1):
        h = hashlib.sha1(",".join(map(str, ids)).encode()).hexdigest()[:16]
        ruta = os.path.join(ip.LOTES, h + ".json.gz")
        if os.path.exists(ruta):
            metas = ip.leer_gzip(ruta)
            fuente = "caché"
        else:
            metas, _ = ip.pedir(ids, pausa)
            if metas is None:
                print("  trozo %s FALLÓ" % h)
                continue
            ip.escribir_gzip(ruta, metas)
            fuente = "red"
        n = ip.ingerir(con, metas, coste, etiqueta)
        con.execute("INSERT OR REPLACE INTO lotes (hash,n_ids,n_part,bytes,ts) "
                    "VALUES (?,?,?,?,?)",
                    (h, len(ids), n, os.path.getsize(ruta),
                     dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")))
        con.commit()
        print("  %d/%d %s %s %d/%d" % (k, len(trozos), h, fuente, n, len(ids)), flush=True)
    tot = con.execute("SELECT count(*) FROM partidas").fetchone()[0]
    print("total ahora:", tot)
    return 0


if __name__ == "__main__":
    sys.exit(main())

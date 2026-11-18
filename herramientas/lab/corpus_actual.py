#!/usr/bin/env python3
"""Arma un corpus de evaluación con partidas del PARCHE ACTUAL.

El `data/replay_cache.json` del proyecto son 626 partidas anteriores al 30-oct: medir el
motor ahí es medirlo contra otra meta. Este export toma partidas de `lab.db` (20 500 del
parche) y las deja en el mismo formato que espera `herramientas/evaluar_motor.py`, así que
el A/B se puede correr sobre la meta que el motor dice seguir.

Formato de salida (una partida por jugador de Abrams):
    match_id, duracion_s, gane, yo: {slot, team, items:[{t,id,vendido}],
                                     stats:[{t,neto}]}, jugadores:[{slot,team,hero}]

Equipo: `player_slot // 6` (0-5 y 6-11), que es el reparto de Deadlock. `net_worth_at_buy`
viene cuantizado, así que la curva de almas es a escalones; sirve para condicionar el
estado, no para calcular ETAs.

Uso:
    python3 herramientas/lab/corpus_actual.py --partidas 2000
    python3 herramientas/evaluar_motor.py --cache data/replay_actual.json
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from herramientas.lab import db  # noqa: E402

SALIDA = os.path.join(RAIZ, "data", "replay_actual.json")
HEROE = 6


def main():
    ap = argparse.ArgumentParser(description="Corpus de evaluación del parche actual")
    ap.add_argument("--db", default=db.RUTA)
    ap.add_argument("--partidas", type=int, default=2000)
    ap.add_argument("--salida", default=SALIDA)
    args = ap.parse_args()

    con = db.conectar(args.db)
    mids = [r["match_id"] for r in con.execute(
        "SELECT DISTINCT c.match_id FROM compras_api c "
        "JOIN jugadores_api j ON j.match_id=c.match_id AND j.player_slot=c.player_slot "
        "WHERE j.hero_id=? ORDER BY c.match_id LIMIT ?", (HEROE, args.partidas))]
    if not mids:
        print("sin partidas en la base: corre ingesta_api.py")
        return 1

    salida = []
    for mid in mids:
        meta = con.execute("SELECT duracion_s FROM partidas_api WHERE match_id=?",
                           (mid,)).fetchone()
        jugadores = [dict(r) for r in con.execute(
            "SELECT player_slot, hero_id, ganador FROM jugadores_api WHERE match_id=? "
            "ORDER BY player_slot", (mid,))]
        mio = next((j for j in jugadores if j["hero_id"] == HEROE), None)
        if not mio:
            continue
        compras = [dict(r) for r in con.execute(
            "SELECT t, item_id, vendido_t, net_worth FROM compras_api "
            "WHERE match_id=? AND player_slot=? ORDER BY orden",
            (mid, mio["player_slot"]))]
        if len(compras) < 5:
            continue
        items, stats, vistos = [], [], set()
        for c in compras:
            items.append({"t": int(c["t"]), "id": str(c["item_id"]),
                          "vendido": int(c["vendido_t"] or 0)})
            clave = (int(c["t"]), int(c["net_worth"] or 0))
            if clave not in vistos:
                vistos.add(clave)
                stats.append({"t": int(c["t"]), "neto": int(c["net_worth"] or 0)})
        # La curva de almas de los otros 11 también hace falta: sin ella el motor no
        # puede saber si vas atrás y los perfiles "atras"/"arriba" nunca se activan.
        curvas = {}
        for j in jugadores:
            anclas, vistos_j = [], set()
            for c in con.execute(
                    "SELECT t, net_worth FROM compras_api WHERE match_id=? AND "
                    "player_slot=? ORDER BY orden", (mid, j["player_slot"])):
                clave = (int(c["t"]), int(c["net_worth"] or 0))
                if clave in vistos_j:
                    continue
                vistos_j.add(clave)
                anclas.append({"t": int(c["t"]), "neto": int(c["net_worth"] or 0)})
            curvas[j["player_slot"]] = anclas
        salida.append({
            "match_id": mid,
            "duracion_s": (meta["duracion_s"] if meta else 0) or 0,
            "gane": bool(mio["ganador"]),
            "yo": {"slot": mio["player_slot"], "team": mio["player_slot"] // 6,
                   "items": items, "stats": stats},
            "jugadores": [{"slot": j["player_slot"], "team": j["player_slot"] // 6,
                           "hero": j["hero_id"],
                           "stats": curvas.get(j["player_slot"], [])}
                          for j in jugadores],
        })

    with open(args.salida, "w", encoding="utf-8") as f:
        json.dump(salida, f)
    dur = collections.Counter(s["duracion_s"] // 600 * 10 for s in salida)
    print(f"{len(salida)} partidas → {os.path.relpath(args.salida, RAIZ)} "
          f"({os.path.getsize(args.salida) / 1e6:.1f} MB)")
    print("duración (decenas de min):", sorted(dur.items())[:6])
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Puerta de calidad por resultado: ¿lo que recomienda el motor valía más que lo que compró?

El `--motor` de `mi_camino.py` mide **acuerdo** (¿acertó lo que Diego compró?). Eso es
una métrica de popularidad, no de valor: si Diego compra fuera de meta, el motor acierta
menos por hacerlo mejor. Este script mide otra cosa:

    ΔW(comprado)  −  ΔW(recomendado)

donde ΔW sale de las 20 500 partidas reales: cuánto gana de más un ítem respecto a la
probabilidad base de su estado (minuto × almas). Si el delta es **negativo**, el motor
proponía algo que, en partidas parecidas, ganaba más que lo comprado.

Emparejamiento: primero se busca ΔW del ítem en la misma celda de estado con n ≥ 30; si
no alcanza, se usa el ΔW global del ítem; si tampoco hay n, el par se descarta y se dice.

Uso:
    python3 herramientas/lab/fixture_delta_w.py
    python3 herramientas/lab/fixture_delta_w.py --config '{"aperturas": 3}'
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import statistics
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from herramientas.lab import db                      # noqa: E402
from herramientas.mi_camino import (                 # noqa: E402
    jugables, leer, nombres, sesiones)

ITEMS = os.path.join(RAIZ, "data", "items.json")


def celda(t, almas):
    return (min(int(t // 360), 5), min(int(almas // 6000), 6))


def modelo_dw(con, heroe=6):
    """{(item_id, celda): ΔW} y {item_id: ΔW}, con el mismo modelo que ensayos_api."""
    filas = [dict(r) for r in con.execute("""
        SELECT c.t, c.coste, c.item_id, c.net_worth, j.ganador
          FROM compras_api c
          JOIN jugadores_api j
            ON j.match_id = c.match_id AND j.player_slot = c.player_slot
         WHERE j.hero_id = ? AND c.coste > 0
    """, (heroe,))]
    glob = sum(f["ganador"] for f in filas) / len(filas)
    celdas = collections.defaultdict(lambda: [0, 0])
    for f in filas:
        c = celdas[celda(f["t"], f["net_worth"])]
        c[0] += f["ganador"]
        c[1] += 1
    P = {k: (v[0] + 20 * glob) / (v[1] + 20) for k, v in celdas.items()}
    por_celda = collections.defaultdict(list)
    por_item = collections.defaultdict(list)
    for f in filas:
        r = f["ganador"] - P[celda(f["t"], f["net_worth"])]
        por_celda[(f["item_id"], celda(f["t"], f["net_worth"]))].append(r)
        por_item[f["item_id"]].append(r)
    dw_celda = {k: sum(v) / len(v) for k, v in por_celda.items() if len(v) >= 30}
    dw_item = {k: sum(v) / len(v) for k, v in por_item.items() if len(v) >= 100}
    return dw_celda, dw_item


def dw_de(iid, t, almas, dw_celda, dw_item):
    c = celda(t, almas)
    if (iid, c) in dw_celda:
        return dw_celda[(iid, c)], "celda"
    if iid in dw_item:
        return dw_item[iid], "ítem"
    return None, None


def main():
    ap = argparse.ArgumentParser(description="ΔW de lo comprado vs lo recomendado")
    ap.add_argument("--db", default=db.RUTA)
    ap.add_argument("--config", default=None)
    ap.add_argument("--heroe", type=int, default=6)
    args = ap.parse_args()

    import sys as _sys
    _sys.path.insert(0, RAIZ)
    from coach.motor_api import Motor            # noqa: PLC0415

    con = db.conectar(args.db)
    dw_celda, dw_item = modelo_dw(con, args.heroe)
    motor = Motor(json.loads(args.config) if args.config else None)
    nom = nombres()
    ids = {v: k for k, v in nom.items()}

    ses = jugables(sesiones(leer()))
    pares = []
    for s in ses:
        previo = None
        for r in s:
            actual = set(str(i) for i in (r.get("items") or ()))
            if previo is not None and actual and r.get("t") is not None:
                nuevos = actual - previo
                if nuevos:
                    almas = r.get("almas") or 0
                    rec = motor.analizar_dict({
                        "t": r.get("t"), "yo": {"heroe": "Abrams",
                        "almas": almas, "items": sorted(previo)}})
                    lista = [x.get("nombre") for x in (rec.get("recomendaciones") or [])]
                    if lista and lista[0] in ids:
                        for iid in nuevos:
                            a, fa = dw_de(iid, r["t"], almas, dw_celda, dw_item)
                            b, fb = dw_de(ids[lista[0]], r["t"], almas, dw_celda, dw_item)
                            if a is None or b is None:
                                continue
                            pares.append((nom[iid], lista[0], (a - b) * 100, fa, fb))
            if actual:
                previo = actual

    if not pares:
        print("sin pares comparables (faltan n en la base de partidas)")
        return 1
    deltas = [p[2] for p in pares]
    media = statistics.mean(deltas)
    print(f"pares {len(pares)} · ΔW(comprado) − ΔW(recomendado) = {media:+.2f} pp")
    print(f"mediana {statistics.median(deltas):+.2f} pp · "
          f"mejora el motor en {sum(1 for d in deltas if d < 0)}/{len(deltas)} compras")
    por_motivo = collections.Counter(p[3] for p in pares)
    print("emparejamiento:", dict(por_motivo))
    print("\npeores (el motor proponía algo mucho mejor):")
    for c, r, d, _, _ in sorted(pares, key=lambda x: x[2])[:5]:
        print(f"  compró {c[:22]:24s} motor {r[:22]:24s} {d:+7.1f} pp")
    print("\nmejores (Diego compró mejor que el motor):")
    for c, r, d, _, _ in sorted(pares, key=lambda x: -x[2])[:5]:
        print(f"  compró {c[:22]:24s} motor {r[:22]:24s} {d:+7.1f} pp")
    return 0


if __name__ == "__main__":
    sys.exit(main())

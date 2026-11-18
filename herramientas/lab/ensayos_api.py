#!/usr/bin/env python3
"""Ensayos sobre las partidas reales del parche (tablas *_api de lab.db).

La diferencia con `ensayos.py`: allí se mide winrate de subgrupos; aquí se mide **ΔW**,
el cambio de probabilidad de ganar atribuible a una compra *en el estado en que se hizo*.
Es la métrica que pide el marco de otros MOBA (Riot August, tesis de xPetu): el winrate
crudo premia al que compra tarde porque llegar tarde con oro ya implica que vas ganando.

Modelo de estado, deliberadamente simple y explícito:
    P(ganar | minuto, net worth al comprar)   con celdas de 6 min × 6 000 almas
    ΔW(ítem) = media de (ganó − P(estado)) sobre sus compras

Tres reglas del marco:
    R1  re-ranking crudo vs condicionado (Spearman)
    R3  ΔW por buckets de déficit de almas (¿qué rinde yendo abajo?)
    R4  eficiencia por tier: ΔW por 1 000 almas a reloj fijo

Uso:
    python3 herramientas/lab/ensayos_api.py
    python3 herramientas/lab/ensayos_api.py --heroe 6 --min-n 200
    python3 herramientas/lab/ensayos_api.py --json
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

from herramientas.lab import db  # noqa: E402

ITEMS = os.path.join(RAIZ, "data", "items.json")


def nombres():
    with open(ITEMS, encoding="utf-8") as f:
        d = json.load(f)
    v = d.values() if isinstance(d, dict) else d
    return {str(x["id"]): x.get("name") or str(x["id"]) for x in v}


def carga(con, heroe):
    q = """
      SELECT c.match_id, c.player_slot, c.orden, c.t, c.item_id, c.coste,
             c.net_worth, j.ganador
        FROM compras_api c
        JOIN jugadores_api j
          ON j.match_id = c.match_id AND j.player_slot = c.player_slot
       WHERE c.coste > 0 AND j.hero_id = ?
    """
    return [dict(r) for r in con.execute(q, (heroe,))]


def spearman(a, b):
    ra = {k: i for i, k in enumerate(sorted(a, key=a.get))}
    rb = {k: i for i, k in enumerate(sorted(b, key=b.get))}
    n = len(a)
    d2 = sum((ra[k] - rb[k]) ** 2 for k in a)
    return 1 - 6 * d2 / (n * (n * n - 1)) if n > 2 else float("nan")


def estado(t, nw):
    return (min(int(t // 360), 5), min(int(nw // 6000), 6))


def modelo(filas):
    """P(ganar | celda) con suavizado hacia la media global (Laplace ligero)."""
    glob = sum(f["ganador"] for f in filas) / len(filas)
    celdas = collections.defaultdict(lambda: [0, 0])
    for f in filas:
        c = celdas[estado(f["t"], f["net_worth"])]
        c[0] += f["ganador"]
        c[1] += 1
    return {k: (v[0] + 20 * glob) / (v[1] + 20) for k, v in celdas.items()}, glob


def main():
    ap = argparse.ArgumentParser(description="ΔW sobre partidas reales")
    ap.add_argument("--db", default=db.RUTA)
    ap.add_argument("--heroe", type=int, default=6)
    ap.add_argument("--min-n", type=int, default=200)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    con = db.conectar(args.db)
    db.crear_esquema(con)
    filas = carga(con, args.heroe)
    if not filas:
        print("no hay compras del héroe en la base: corre ingesta_api.py")
        return 1
    nom = nombres()
    P, glob = modelo(filas)
    print(f"compras {len(filas):,} · jugadores {len(filas) and len({(f['match_id'], f['player_slot']) for f in filas}):,} "
          f"· partidas {len({f['match_id'] for f in filas}):,} · WR base {glob:.1%}")

    for f in filas:
        f["residuo"] = f["ganador"] - P[estado(f["t"], f["net_worth"])]

    por = collections.defaultdict(list)
    crudo = collections.defaultdict(lambda: [0, 0])
    for f in filas:
        por[f["item_id"]].append(f["residuo"])
        crudo[f["item_id"]][0] += f["ganador"]
        crudo[f["item_id"]][1] += 1
    items = [i for i in por if len(por[i]) >= args.min_n]
    if not items:
        print(f"ningún ítem llega a n>={args.min_n}")
        return 1

    wr = {i: crudo[i][0] / crudo[i][1] for i in items}
    dw = {i: sum(por[i]) / len(por[i]) for i in items}
    rho = spearman(wr, dw)

    print(f"\nR1 · crudo vs condicionado: Spearman {rho:+.2f} sobre {len(items)} ítems "
          f"(n≥{args.min_n})")
    orden_wr = sorted(items, key=lambda i: -wr[i])
    orden_dw = sorted(items, key=lambda i: -dw[i])
    solape = len(set(orden_wr[:10]) & set(orden_dw[:10]))
    print(f"     top-10 coincide en {solape}/10 posiciones")

    print(f"\n{'#':>2} por ΔW{'':22s}{'ΔW':>8}{'WR':>8}{'n':>7}")
    for i in orden_dw[:10]:
        print(f"   {nom.get(i, i)[:26]:28s}{dw[i]*100:+7.1f}pp{wr[i]:8.1%}{len(por[i]):8,}")

    # R3 · déficit de almas: comparar el net worth propio contra la mediana de la
    # partida en ese minuto (±90 s). Es un proxy honesto: no tenemos el oro del equipo.
    por_partida = collections.defaultdict(list)
    for f in filas:
        por_partida[f["match_id"]].append((f["t"], f["net_worth"]))
    for f in filas:
        otros = [nw for t, nw in por_partida[f["match_id"]] if abs(t - f["t"]) <= 90]
        f["deficit"] = f["net_worth"] - (statistics.median(otros) if otros else f["net_worth"])

    cortes = [(-1e9, -6000, "−6k o más"), (-6000, -2000, "−6k…−2k"),
              (-2000, 2000, "parejo"), (2000, 6000, "+2k…+6k"), (6000, 1e9, "+6k o más")]
    print("\nR3 · ΔW por posición de almas (todas las compras del héroe)")
    print(f"{'bucket':14s}{'n':>9}{'ΔW':>9}{'WR':>8}")
    for lo, hi, eti in cortes:
        sel = [f for f in filas if lo <= f["deficit"] < hi]
        if not sel:
            continue
        print(f"{eti:14s}{len(sel):9,}{sum(f['residuo'] for f in sel)/len(sel)*100:+8.1f}pp"
              f"{sum(f['ganador'] for f in sel)/len(sel):8.1%}")

    # R4 · eficiencia por tier a reloj fijo
    print("\nR4 · ΔW por 1 000 almas, por tier y reloj")
    print(f"{'reloj':10s}{'800':>9}{'1600':>9}{'3200':>9}{'6400':>9}")
    for lo, hi, eti in ((0, 600, "0–10 min"), (600, 1200, "10–20 min"),
                        (1200, 1800, "20–30 min"), (1800, 1e9, "30+ min")):
        fila = []
        for coste in (800, 1600, 3200, 6400):
            sel = [f for f in filas if lo <= f["t"] < hi and f["coste"] == coste]
            fila.append(f"{sum(f['residuo'] for f in sel)/len(sel)/coste*1000*100:+8.1f}"
                        if len(sel) >= 30 else f"{'—':>9}")
        print(f"{eti:10s}" + "".join(fila))

    if args.json:
        print(json.dumps({"spearman": rho, "items": {
            nom.get(i, i): {"dw": dw[i], "wr": wr[i], "n": len(por[i])} for i in items
        }}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

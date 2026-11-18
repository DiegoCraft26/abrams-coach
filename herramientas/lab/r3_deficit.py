#!/usr/bin/env python3
"""R3 · ¿Qué rinde yendo abajo? Con déficit de equipo real, no proxy.

En la primera pasada esta regla quedó bloqueada: `net_worth_at_buy` sólo dice el oro del
jugador y el 98 % de las compras caía en «parejo». Pero la base trae las compras de los
**12 jugadores** de cada partida, cada una con su net worth. Con eso se reconstruye el oro
de cada equipo en el instante de cada compra (último ancla conocida ≤ t) y el déficit de
verdad:

    déficit = Σ net_worth de mi equipo − Σ net_worth del rival

Luego se mide ΔW (igual que `ensayos_api.py`) por tramo de déficit y, dentro del tramo
«voy abajo», qué ítems rinden.

Uso:
    python3 herramientas/lab/r3_deficit.py --max-partidas 5000
    python3 herramientas/lab/r3_deficit.py --max-partidas 5000 --min-n 200
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


def tramo(d):
    if d <= -6000:
        return "−6k o más"
    if d <= -2000:
        return "−6k…−2k"
    if d < 2000:
        return "parejo"
    if d < 6000:
        return "+2k…+6k"
    return "+6k o más"


def nw_en(anclas, t):
    """Último net worth conocido del jugador en o antes de t."""
    if not anclas:
        return None
    previo = None
    for ta, nw in anclas:
        if ta > t:
            break
        previo = nw
    return previo if previo is not None else anclas[0][1]


def main():
    ap = argparse.ArgumentParser(description="ΔW por déficit de equipo (R3)")
    ap.add_argument("--db", default=db.RUTA)
    ap.add_argument("--heroe", type=int, default=6)
    ap.add_argument("--max-partidas", type=int, default=5000)
    ap.add_argument("--min-n", type=int, default=160)
    ap.add_argument("--json", default=None,
                    help="ruta para exportar el ΔW yendo atrás por ítem")
    args = ap.parse_args()

    con = db.conectar(args.db)
    mids = [r["match_id"] for r in con.execute(
        "SELECT DISTINCT c.match_id FROM compras_api c "
        "JOIN jugadores_api j ON j.match_id=c.match_id AND j.player_slot=c.player_slot "
        "WHERE j.hero_id=? ORDER BY c.match_id LIMIT ?", (args.heroe, args.max_partidas))]
    if not mids:
        print("sin partidas: corre ingesta_api.py")
        return 1
    print(f"partidas {len(mids):,}")

    # Pasada 1: P(ganar | minuto, net worth propio) con todas las compras del héroe.
    glob = [0, 0]
    celdas = collections.defaultdict(lambda: [0, 0])
    filas = con.execute("""
        SELECT c.t, c.net_worth, j.ganador
          FROM compras_api c
          JOIN jugadores_api j ON j.match_id=c.match_id AND j.player_slot=c.player_slot
         WHERE j.hero_id=? AND c.coste>0
    """, (args.heroe,))
    for t, nw, g in filas:
        k = (min(int(t // 360), 5), min(int(nw // 6000), 6))
        celdas[k][0] += g
        celdas[k][1] += 1
        glob[0] += g
        glob[1] += 1
    base = glob[0] / glob[1]
    P = {k: (v[0] + 20 * base) / (v[1] + 20) for k, v in celdas.items()}
    print(f"WR base {base:.1%} · celdas {len(P)}")

    # Pasada 2: por partida, reconstruir anclas de los 12 jugadores y guardar cada
    # compra de Abrams con su déficit de equipo. Sin el déficit en el modelo, el
    # residual de cada tramo sólo repite «los que van abajo pierden más», que es
    # tautología y no responde qué comprar yendo atrás.
    filas_ok = []
    procesadas = 0
    for mid in mids:
        jugadores = {r["player_slot"]: dict(r) for r in con.execute(
            "SELECT player_slot, hero_id, ganador FROM jugadores_api WHERE match_id=?",
            (mid,))}
        filas_m = [dict(r) for r in con.execute(
            "SELECT player_slot, t, net_worth, item_id FROM compras_api "
            "WHERE match_id=? AND coste>0 ORDER BY player_slot, orden", (mid,))]
        anclas = collections.defaultdict(list)
        for f in filas_m:
            anclas[f["player_slot"]].append((f["t"], f["net_worth"] or 0))
        mio = next((s for s, j in jugadores.items() if j["hero_id"] == args.heroe), None)
        if mio is None or not 0 <= mio < 12:
            continue
        procesadas += 1
        mi_team = mio // 6
        punteros = {slot: 0 for slot in jugadores}
        actual = {slot: (anclas[slot][0][1] if anclas.get(slot) else None)
                  for slot in jugadores}
        for f in filas_m:
            if f["player_slot"] != mio:
                continue
            t = f["t"]
            for slot in jugadores:
                lista = anclas.get(slot) or []
                i = punteros[slot]
                while i + 1 < len(lista) and lista[i + 1][0] <= t:
                    i += 1
                punteros[slot] = i
                actual[slot] = lista[i][1] if lista else None
            suma = {0: 0, 1: 0}
            for slot, v in actual.items():
                if v is not None and 0 <= slot < 12:
                    suma[slot // 6] += v
            deficit = suma[mi_team] - suma[1 - mi_team]
            filas_ok.append((f["t"], f["net_worth"] or 0, deficit,
                             jugadores[mio]["ganador"], f["item_id"]))
    print(f"partidas procesadas {procesadas:,} · compras {len(filas_ok):,}")

    # El estado ahora incluye el déficit: P(ganar | minuto, oro propio, déficit).
    glob2 = [0, 0]
    celdas2 = collections.defaultdict(lambda: [0, 0])
    for t, nw, d, g, _ in filas_ok:
        k = (min(int(t // 360), 5), min(int(nw // 6000), 6), tramo(d))
        celdas2[k][0] += g
        celdas2[k][1] += 1
        glob2[0] += g
        glob2[1] += 1
    base2 = glob2[0] / glob2[1]
    P2 = {k: (v[0] + 20 * base2) / (v[1] + 20) for k, v in celdas2.items()}
    print(f"WR base {base2:.1%} · celdas {len(P2)}")

    por_tramo = collections.defaultdict(lambda: [0.0, 0])
    por_item = collections.defaultdict(lambda: [0.0, 0])
    for t, nw, d, g, iid in filas_ok:
        k = (min(int(t // 360), 5), min(int(nw // 6000), 6), tramo(d))
        r = g - P2[k]
        tr = tramo(d)
        por_tramo[tr][0] += r
        por_tramo[tr][1] += 1
        it = por_item[(tr, iid)]
        it[0] += r
        it[1] += 1

    print(f"\n{'tramo de déficit':16s}{'n':>9}{'ΔW':>9}   (condicionado al déficit)")
    for k in ("−6k o más", "−6k…−2k", "parejo", "+2k…+6k", "+6k o más"):
        s_, n = por_tramo[k]
        if n:
            print(f"{k:16s}{n:9,}{s_/n*100:+8.1f}pp")

    datos = json.load(open(os.path.join(RAIZ, "data", "items.json")))
    nom = {str(v["id"]): v.get("name") for v in datos.values()}
    atras = [(iid, v) for (k, iid), v in por_item.items()
             if k in ("−6k o más", "−6k…−2k") and v[1] >= args.min_n]
    if args.json and atras:
        import time as _t
        datos = {str(iid): {"dw": round(v[0] / v[1], 5), "n": v[1]}
                 for iid, v in atras}
        valores = [x["dw"] for x in datos.values()]
        lo, hi = min(valores), max(valores)
        rango = (hi - lo) or 1.0
        for x in datos.values():
            x["norm"] = round((x["dw"] - lo) / rango * 2 - 1, 4)
        salida = {"generado": _t.strftime("%Y-%m-%dT%H:%M:%S"),
                  "fuente": "r3_deficit.py", "partidas": procesadas,
                  "items": datos}
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(salida, f, ensure_ascii=False, indent=1)
        print(f"\nexportado {len(datos)} ítems → {args.json}")
    if atras:
        print(f"\nÍtems que rinden YENDO ATRÁS (n≥{args.min_n})")
        for iid, (s_, n) in sorted(atras, key=lambda kv: -kv[1][0] / kv[1][1])[:10]:
            print(f"  {str(nom.get(str(iid)) or iid)[:26]:28s}{s_/n*100:+6.1f}pp  n={n:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Valida el camino de build sobre partidas reales.

Mide lo que se nota jugando: cuántos ítems de 800 recomienda el motor en los primeros
10 minutos (antes 4-5), cuántas veces toca comprar/ahorrar/vender y cuánto tarda.

Uso:
    python3 herramientas/validar_camino.py --partidas 626
    python3 herramientas/validar_camino.py --cache data/replay_muestra.json --partidas 60
"""
import argparse
import json
import os
import statistics
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from herramientas.evaluar_motor import CACHE, almas_en, estado_en  # noqa: E402
from coach.motor_api import Motor  # noqa: E402


def cargar(limite, ruta):
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)
    return datos[:limite] if limite else datos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--partidas", type=int, default=626)
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--paso", type=int, default=30,
                    help="cada cuántos segundos se consulta el motor (default 30)")
    a = ap.parse_args()

    partidas = cargar(a.partidas, a.cache)
    heroes = {k: v["nombre"].lower().replace(" ", "_")
              for k, v in json.load(open(os.path.join(RAIZ, "data", "heroes.json"))).items()}
    motor = Motor()
    # Una consulta de calentamiento: la primera construye el camino y carga perezosa.
    motor.analizar_dict(estado_en(partidas[0], 0, heroes))
    por_partida, acciones, modos, etas, latencias = [], {}, {}, [], []
    for partida in partidas:
        vistos = set()
        for t in range(0, 1500, a.paso):
            est = estado_en(partida, t, heroes)
            t0 = time.perf_counter()
            r = motor.analizar_dict(est)
            latencias.append((time.perf_counter() - t0) * 1000)
            d = r.get("decision") or {}
            acciones[d.get("accion", "?")] = acciones.get(d.get("accion", "?"), 0) + 1
            modos[d.get("modo") or "?"] = modos.get(d.get("modo") or "?", 0) + 1
            if d.get("eta_s"):
                etas.append(d["eta_s"])
            item = d.get("item") or {}
            if t < 600 and item.get("costo") == 800:
                vistos.add(item.get("id"))
        por_partida.append(len(vistos))

    total = max(1, len(partidas))
    media = sum(por_partida) / total
    orden = sorted(por_partida)
    p90 = orden[int(0.9 * (len(orden) - 1))]
    print(f"partidas ................. {len(partidas)}")
    print(f"ítems de 800 (0-10 min) .. media {media:.2f} · mediana "
          f"{statistics.median(por_partida):.0f} · p90 {p90} · máx {max(por_partida)}")
    total_acc = sum(acciones.values()) or 1
    for k in ("COMPRAR", "AHORRAR", "VENDER"):
        print(f"{k:<25} {acciones.get(k, 0)*100/total_acc:5.1f}%")
    print("modos de ahorro ......... " + " · ".join(
        f"{k} {v*100/total_acc:.0f}%" for k, v in sorted(modos.items()) if k in ("ahorro", "rush", "farm")))
    if etas:
        print(f"ETA (s) .................. mediana {statistics.median(etas):.0f} · "
              f"p90 {sorted(etas)[int(0.9*(len(etas)-1))]} · máx {max(etas)}")
    lat_ord = sorted(latencias)
    p99 = lat_ord[int(0.99 * (len(lat_ord) - 1))]
    print(f"latencia ................. {statistics.fmean(latencias):.2f} ms medio · "
          f"p99 {p99:.2f} · máx {max(latencias):.2f}")

    fallos = []
    if media > 3.0:
        fallos.append(f"media de 800 en 10 min = {media:.2f} (> 3)")
    if p90 > 3:
        fallos.append(f"p90 de 800 en 10 min = {p90} (> 3)")
    if p99 > 12.0:
        fallos.append(f"latencia p99 {p99:.1f} ms (> 12)")
    if fallos:
        print("\nFALLA: " + "; ".join(fallos))
        return 1
    print("\nOK: el camino no abusa de los 800 y cabe en el presupuesto de latencia")
    return 0


if __name__ == "__main__":
    sys.exit(main())

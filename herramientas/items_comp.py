#!/usr/bin/env python3
"""Qué compra el Abrams que gana contra una composición enemiga.

    python3 herramientas/items_comp.py --resumen
    python3 herramientas/items_comp.py --enemigos graves,rat_king --min-n 200
    python3 herramientas/items_comp.py --enemigos graves --desde 900 --top 12

Necesita `data/archivo/*items-*.jsonl.gz` (herramientas/archivo_abrams.py --con-items).
Sin esos datos no inventa nada: lo dice y sale.
"""
import argparse
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import historico as H                                # noqa: E402
from coach import items_comp as IC                              # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enemigos", default="", help="ids o nombres separados por coma")
    ap.add_argument("--min-n", type=int, default=IC.MIN_N)
    ap.add_argument("--desde", type=int, default=0, help="segundo mínimo de compra")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--heroe", default="abrams", help="héroe del que se leen las compras")
    ap.add_argument("--resumen", action="store_true")
    a = ap.parse_args()

    nombres_tabla = H.nombre_a_id()
    heroe = (int(a.heroe) if str(a.heroe).isdigit()
             else nombres_tabla.get(str(a.heroe).lower(), 6))
    partidas = IC.cargar(heroe=heroe)
    if not partidas:
        print("sin datos: corre herramientas/archivo_abrams.py --con-items")
        return 2

    total = len(partidas)
    gano = sum(1 for p in partidas if IC._gano(p))
    print(f"{total} partidas con compras · winrate base {gano/total:.1%}")
    if a.resumen:
        print(f"composiciones distintas: {len({IC.enemigos_de(p) for p in partidas})}")

    if not a.enemigos:
        if not a.resumen:
            print("pasa --enemigos o --resumen")
        return 0

    nombres = H.nombres()
    traduccion = H.nombre_a_id()
    ids = []
    for x in a.enemigos.split(","):
        x = x.strip()
        if not x:
            continue
        if x.isdigit():
            ids.append(int(x))
        elif x.lower() in traduccion:
            ids.append(traduccion[x.lower()])
        else:
            print(f"héroe desconocido: {x}")
            return 2

    tabla = IC.comparar(partidas, ids, min_n=a.min_n)
    if not tabla["n_partidas"]:
        print("ninguna partida con esa composición en el archivo")
        return 0
    print(f"\ncontra {', '.join(nombres.get(h, str(h)) for h in ids)}: "
          f"{tabla['n_partidas']} partidas · winrate base de ESA comp "
          f"{tabla['base']:.1%} (global {tabla['base_global']:.1%})")

    filas = [f for f in tabla["items"] if f["t_mediana_s"] >= a.desde][:a.top]
    if not filas:
        print(f"sin ítems con n≥{a.min_n} y compra después del segundo {a.desde}")
        return 0
    print(f"\n  {'ítem':<24} {'n':>6} {'winrate':>8} {'cota 95%':>9} {'vs base':>8}  compra")
    base = tabla["base"]
    for f in filas:
        delta = (f["wr"] - base) * 100
        print(f"  {f['nombre'][:24]:<24} {f['n']:>6} {f['wr']:>7.1%} {f['lb']:>8.1%} "
              f"{delta:>+7.1f}pp  {f['t_mediana_s']//60}min")
    print("\nOjo: es «aparece en las partidas que ganan», no «comprar esto te hace ganar». "
          "El ítem se compra para responder a lo que ya pasa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

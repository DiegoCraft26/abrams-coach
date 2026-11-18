#!/usr/bin/env python3
"""Qué composiciones se repiten en el banco de Abrams y cuáles se pierden.

    python3 herramientas/variantes.py                    # resumen + pares que ganan/pierden
    python3 herramientas/variantes.py --k 3 --min-n 8    # tríos con muestra
    python3 herramientas/variantes.py --enemigo haze     # solo patrones con Haze
    python3 herramientas/variantes.py --frecuencia       # lo más común, no lo que gana

Sin red: lee `data/replay_cache.json` (626 partidas de Abrams). La plantilla completa casi
nunca se repite (612 composiciones distintas en 614 partidas), así que la unidad útil es el
par o el trío, y siempre se enseña la muestra.
"""
import argparse
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import variantes as V                                # noqa: E402


def _nombre(heroes, h):
    return heroes.get(h, str(h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=2, choices=[2, 3, 5, 6],
                    help="tamaño del patrón (2=pares, 3=tríos, 6=plantilla enemiga)")
    ap.add_argument("--min-n", type=int, default=V.MIN_N,
                    help="muestra mínima para enseñar un patrón")
    ap.add_argument("--enemigo", action="append", default=[],
                    help="héroe que debe estar en el patrón (repetible)")
    ap.add_argument("--frecuencia", action="store_true",
                    help="ordenar por cuántas veces aparece, no por winrate")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--dias", type=int, default=0,
                    help="con --archivo, usar solo partidas de los últimos N días")
    ap.add_argument("--archivo", action="store_true",
                    help="usar data/archivo (miles de partidas) en vez del banco de 626")
    a = ap.parse_args()

    partidas = V.cargar_archivo(dias=a.dias) if a.archivo else V.cargar()
    if not partidas:
        print("no pude leer el banco (data/replay_cache.json) ni el archivo "
              "(data/archivo/*.jsonl.gz)")
        return 2
    heroes = V.nombres()
    indice = V.construir(partidas, k=a.k)
    r = V.resumen(partidas, V.construir(partidas, k=2))

    print(f"banco: {r['partidas']} partidas usables · {r['comps_enemigas_distintas']} "
          f"composiciones enemigas distintas · {r['comps_repetidas']} repetidas "
          f"({r['partidas_en_comp_repetida']} partidas dentro de una repetida)")
    print(f"pares enemigos: {r['pares_distintos']} distintos · mediana "
          f"{r['pares_mediana']} apariciones · {r['pares_con_muestra']} con "
          f"n≥{V.MIN_N}")

    if a.enemigo:
        por_nombre = V.indice_por_nombre()
        filtrados = []
        for e in a.enemigo:
            clave = str(e).strip().lower()
            valor = por_nombre.get(clave) if not clave.isdigit() else int(clave)
            if valor is not None and valor not in filtrados:
                filtrados.append(valor)
        if not filtrados:
            print(f"héroe desconocido: {a.enemigo}")
            return 2
        consulta = V.consultar(indice, enemigos=filtrados, min_n=a.min_n)
        filas = consulta["enemigos"]
        print(f"\npatrones con {', '.join(_nombre(heroes, h) for h in filtrados)} "
              f"(n≥{a.min_n}): {len(filas)}")
    else:
        filas = V.listar(indice, min_n=a.min_n,
                         orden="frecuencia" if a.frecuencia else "cota")
        print(f"\n{len(filas)} patrones de {a.k} con muestra ≥{a.min_n}")

    if filas:
        cabeza = filas[:a.top]
        print(f"  {'n':>4}  {'winrate':>7}  {'cota 95%':>8}  patrón")
        for f in cabeza:
            nombre = ", ".join(_nombre(heroes, h) for h in f["combo"])
            print(f"  {f['n']:>4}  {f['wr']:>6.1%}  {f['lb']:>7.1%}  {nombre}")
    if not a.frecuencia and not a.enemigo:
        print("\nlos que peor se dan (misma muestra mínima):")
        for f in V.listar(indice, min_n=a.min_n, orden="peor")[:5]:
            nombre = ", ".join(_nombre(heroes, h) for h in f["combo"])
            print(f"  {f['n']:>4}  {f['wr']:>6.1%}  {f['lb']:>7.1%}  {nombre}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

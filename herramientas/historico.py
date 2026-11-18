#!/usr/bin/env python3
"""Índice histórico de composiciones desde el archivo local, y consultas.

    python3 herramientas/historico.py --construir            # data/historico.json.gz
    python3 herramientas/historico.py --construir --dias 30  # solo el último mes
    python3 herramientas/historico.py --enemigos haze,graves,rat_king,bebop,seven,ivy
    python3 herramientas/historico.py --resumen

El índice se construye una vez (~2 s con 37 000 partidas) y el coach lo relee al arrancar
en milisegundos. Sin archivo (`data/archivo/`), usa el banco de 626 partidas.
"""
import argparse
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import historico as H                                # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--construir", action="store_true", help="reconstruir el índice")
    ap.add_argument("--dias", type=int, default=0, help="usar solo los últimos N días")
    ap.add_argument("--enemigos", default="", help="ids o nombres separados por coma")
    ap.add_argument("--resumen", action="store_true")
    ap.add_argument("--min-n", type=int, default=H.MIN_N)
    a = ap.parse_args()

    if a.construir:
        indice = H.construir_desde_archivo(dias=a.dias)
        if not indice.get("total"):
            print("no hay partidas: corre herramientas/archivo_abrams.py primero")
            return 2
        ruta = H.guardar(indice)
        pares = len(indice.get("pares") or {})
        comps = len(indice.get("comp") or {})
        print(f"índice: {indice['total']} partidas · {comps} plantillas · {pares} pares "
              f"· guardado en {os.path.relpath(ruta, RAIZ)} "
              f"({os.path.getsize(ruta)/1024:.0f} kB)")
        H._CACHE.update({"indice": indice, "ts": 0.0})

    if a.resumen or not a.enemigos:
        indice = H.indice(0)
        total = indice.get("total") or 0
        if not total:
            print("sin índice: corre --construir")
            return 2
        base = (indice.get("victorias") or 0) / total
        pares = indice.get("pares") or {}
        con_muestra = sum(1 for v in pares.values() if v[0] >= a.min_n)
        print(f"\n{total} partidas · winrate base {base:.1%}")
        print(f"plantillas distintas: {len(indice.get('comp') or {})}")
        print(f"pares distintos: {len(pares)} · con n≥{a.min_n}: {con_muestra}")
        repetidas = sorted(((v[0], k) for k, v in (indice.get("comp") or {}).items()),
                           reverse=True)[:3]
        for n, clave in repetidas:
            print(f"  plantilla más repetida: {n}x {clave}")
        peores = sorted(((v[1] / v[0], v[0], k) for k, v in pares.items()
                         if v[0] >= a.min_n))[:5]
        print("\nlos pares que peor se dan (winrate, n, par):")
        tabla = H.nombres()
        for wr, n, clave in peores:
            print(f"  {wr:5.1%}  n={n:<5} {H._nombres_de(clave.split(','), tabla)}")

    if a.enemigos:
        lista = [x.strip() for x in a.enemigos.split(",") if x.strip()]
        r = H.consultar(H.indice(0), lista, min_n=a.min_n)
        print(f"\nconsulta: {', '.join(lista)}")
        if not r["aviso"]:
            print("  sin datos suficientes para esta composición")
        else:
            print(f"  {r['aviso']}")
            tabla = H.nombres()
            for p in r["pares"]:
                print(f"  par {H._nombres_de(p['combo'], tabla)}: {p['wr']:.1%} "
                      f"en {p['n']} (cota 95 % {p['lb']:.1%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

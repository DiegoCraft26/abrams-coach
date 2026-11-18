#!/usr/bin/env python3
"""Camino de compra de un héroe, derivado de sus partidas (no de una guía).

    python3 herramientas/camino_heroe.py --heroe abrams
    python3 herramientas/camino_heroe.py --heroe haze --guardar
    python3 herramientas/camino_heroe.py --heroe abrams --ganadoras

Necesita `data/archivo/heroe-<id>-items-*.jsonl.gz` (herramientas/archivo_abrams.py
--heroe <id> --con-items). Sin datos, lo dice y no inventa.

Dos lecturas y para qué sirve cada una:

- sin `--ganadoras`: lo que se compra (el meta observado). Es lo que usa el camino.
- con `--ganadoras`: lo que se compra en las partidas que se ganan. Sirve para preguntar
  «¿y esto funciona?», no para describir la norma.
"""
import argparse
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import camino_heroe as C                                # noqa: E402
from coach import historico as H                                   # noqa: E402
from coach import items_comp as IC                                 # noqa: E402


def resolver(nombre):
    if str(nombre).isdigit():
        return int(nombre)
    tabla = H.nombre_a_id()
    clave = str(nombre).strip().lower()
    if clave in tabla:
        return tabla[clave]
    raise SystemExit(f"héroe desconocido: {nombre}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--heroe", required=True)
    ap.add_argument("--ganadoras", action="store_true",
                    help="derivar solo de partidas ganadas (¿qué funciona?)")
    ap.add_argument("--guardar", action="store_true")
    ap.add_argument("--min-n", type=int, default=0, help="bajar la muestra mínima")
    a = ap.parse_args()

    hero_id = resolver(a.heroe)
    partidas = IC.cargar(heroe=hero_id)
    if not partidas:
        print(f"sin timelines de {a.heroe} ({hero_id}): "
              f"corre herramientas/archivo_abrams.py --heroe {hero_id} --con-items")
        return 2
    datos = C.derivar(partidas, solo_ganadoras=a.ganadoras,
                      min_n=a.min_n or C.MIN_N)
    if not datos["n_partidas"]:
        print("el archivo existe pero no trae compras usables")
        return 2

    etiqueta = "ganadoras" if a.ganadoras else "todas"
    print(f"{a.heroe} ({hero_id}) · {datos['n_partidas']} partidas {etiqueta}")
    for tramo in ("0-10", "10-20", "20-30", "30+"):
        filas = datos["tramos"].get(tramo) or []
        if not filas:
            continue
        print(f"  {tramo:>5} min: " + " · ".join(
            f"{f['nombre']} ({f['n']})" for f in filas[:5]))
    if datos["primera_compra"]:
        print("  primera compra: " + " · ".join(
            f"{f['nombre']} ({f['n']})" for f in datos["primera_compra"][:3]))

    if a.guardar:
        ruta = C.guardar(hero_id, datos, extra={"fuente": "archivo local de partidas",
                                                "etiqueta": etiqueta})
        print(f"\nguardado: {os.path.relpath(ruta, RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

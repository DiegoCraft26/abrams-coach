#!/usr/bin/env python3
"""Registra el resultado de una o varias partidas en la base local.

Uso:
    python3 herramientas/registrar_resultado.py 132662221
    python3 herramientas/registrar_resultado.py 132662221 --cuenta 123456
    python3 herramientas/registrar_resultado.py --todas
    python3 herramientas/registrar_resultado.py --lista

`--todas` recorre las partidas archivadas que todavía no tienen resultado y las pide a la
API una por una. Si la API falla, sigue con la siguiente: el comando nunca se cae por una
partida que no responda.

Con resultado guardado, `winrate_por_primer_item` (coach/persistencia/repos.py) empieza a
tener datos: winrate real por primer ítem recomendado/comprado.
"""
import argparse
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import resultado as resultado_mod  # noqa: E402
from coach.persistencia.db import conectar, migrar  # noqa: E402
from coach.persistencia.repos import (  # noqa: E402
    Resultado,
    guardar_resultado,
    winrate_por_primer_item,
)


def _faltantes(conexion, limite=None):
    filas = conexion.execute(
        """
        SELECT p.match_id FROM partidas p
        LEFT JOIN resultados r ON r.match_id = p.match_id
        WHERE r.match_id IS NULL
        ORDER BY p.id DESC
        """ + (" LIMIT ?" if limite else ""),
        ((limite,) if limite else ()),
    ).fetchall()
    return [int(f[0]) for f in filas]


def _guardar(conexion, datos):
    conexion.execute("BEGIN")
    guardar_resultado(conexion, Resultado(
        match_id=int(datos["match_id"]),
        win=datos["win"],
        duracion_s=datos["duracion_s"],
        kda=datos["kda"],
        fuente=datos["fuente"],
    ))
    conexion.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("match", nargs="*", type=int, help="match ids a registrar")
    ap.add_argument("--cuenta", type=int, default=None)
    ap.add_argument("--slot", type=int, default=None)
    ap.add_argument("--todas", action="store_true",
                    help="todas las partidas archivadas sin resultado")
    ap.add_argument("--limite", type=int, default=40)
    ap.add_argument("--db", default=None)
    ap.add_argument("--lista", action="store_true", help="resultados ya guardados")
    ap.add_argument("--acierto", action="store_true",
                    help="winrate por primer ítem recomendado/comprado")
    a = ap.parse_args()

    conexion = conectar(a.db)
    migrar(conexion)

    if a.acierto:
        filas = winrate_por_primer_item(conexion)
        if not filas:
            print("sin datos: guarda resultados con `resultado --todas`")
            return 0
        print("winrate por primer ítem (partidas con resultado):")
        for f in filas:
            print(f"  {f['item'][:28]:28} {f['partidas']:>3} partidas · "
                  f"{f['winrate']:.1%}")
        return 0

    if a.lista:
        filas = conexion.execute(
            "SELECT match_id, win, duracion_s, kda, fuente FROM resultados "
            "ORDER BY id DESC LIMIT 25").fetchall()
        if not filas:
            print("sin resultados guardados todavía")
            return 0
        for f in filas:
            print(f"  {f['match_id']}  {'ganada' if f['win'] else 'perdida'}  "
                  f"{f['duracion_s']}s  {f['kda']}  ({f['fuente']})")
        return 0

    ids = list(a.match)
    if a.todas:
        ids += [x for x in _faltantes(conexion, a.limite) if x not in ids]
    if not ids:
        print("nada que registrar: pasa un match id o usa --todas")
        return 0

    guardados, fallidos = 0, []
    for mid in ids:
        datos = resultado_mod.desde_api(mid, cuenta=a.cuenta, slot=a.slot)
        if not datos:
            fallidos.append(mid)
            print(f"  {mid}: sin resultado (API caída, partida privada o héroe ambiguo)")
            continue
        _guardar(conexion, datos)
        guardados += 1
        print(f"  {mid}: {'ganada' if datos['win'] else 'perdida'} · "
              f"{datos['duracion_s']}s · {datos['kda']}")

    if guardados:
        filas = winrate_por_primer_item(conexion)
        if filas:
            print("\nwinrate por primer ítem (con resultado conocido):")
            for f in filas[:10]:
                print(f"  {f['item'][:26]:26} {f['partidas']:>3} partidas · "
                      f"{f['winrate']:.1%}")
    print(f"\nguardados {guardados} · sin resultado {len(fallidos)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

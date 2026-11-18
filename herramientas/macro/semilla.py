#!/usr/bin/env python3
"""Extrae la semilla de cuentas desde la caché de `/v1/matches/metadata`.

Por qué: el leaderboard no sirve como fuente de identidad (los nombres de Steam no son
únicos y `possible_account_ids` es ambiguo). La caché sí trae `account_id` limpio por
jugador y partida, así que de ahí sale la muestra: jugadores que **jugaron Abrams**
(`hero_id == 6`) en alguna de las partidas cacheadas.

Reproducible: deduplica por `match_id`, ordena por `account_id` y muestrea con semilla fija.
No usa red.

Uso:
    python3 herramientas/macro/semilla.py --n 400
    python3 herramientas/macro/semilla.py --n 0        # todas, sin muestreo
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import random
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(RAIZ, "data", "api_cache", "multiheroe")
SALIDA = os.path.join(RAIZ, "datos", "macro", "semilla.json")
ABRAMS = 6
SEMILLA = 20261118


def main():
    ap = argparse.ArgumentParser(description="Semilla de account_ids desde la caché de metadata")
    ap.add_argument("--n", type=int, default=400, help="tamaño de muestra (0 = todas)")
    ap.add_argument("--cache", nargs="+", default=[CACHE],
                    help="uno o más directorios de caché de metadata")
    ap.add_argument("--preferir-rankeadas", action="store_true",
                    help="muestrea primero cuentas vistas en partidas de rango")
    ap.add_argument("--salida", default=SALIDA)
    ap.add_argument("--semilla", type=int, default=SEMILLA)
    args = ap.parse_args()

    rutas = sorted(p for carpeta in args.cache
                   for p in glob.glob(os.path.join(carpeta, "*.json"))
                   if not p.endswith(".meta.json"))
    if not rutas:
        sys.exit(f"no hay ficheros de caché en {args.cache}")

    partidas = {}
    leer_fallidas = []
    for ruta in rutas:
        try:
            with open(ruta, encoding="utf-8") as f:
                datos = json.load(f)
        except (OSError, ValueError) as e:
            leer_fallidas.append(os.path.basename(ruta))
            print(f"  aviso: {os.path.basename(ruta)} ilegible ({e})", file=sys.stderr)
            continue
        if not isinstance(datos, list):
            leer_fallidas.append(os.path.basename(ruta))
            continue
        for m in datos:
            mid = m.get("match_id")
            if mid is None or mid in partidas:
                continue
            partidas[mid] = m

    por_cuenta = {}
    jugadores = 0
    for mid, m in partidas.items():
        ganador = m.get("winning_team")
        arranque = m.get("start_time")
        for pl in m.get("players") or []:
            acc = pl.get("account_id")
            if not acc:
                continue
            jugadores += 1
            if pl.get("hero_id") != ABRAMS:
                continue
            registro = por_cuenta.setdefault(
                acc, {"partidas": [], "ganadas": 0, "rankeada": False})
            if m.get("match_mode") == "Ranked" or (m.get("average_badge") or 0) > 0:
                registro["rankeada"] = True
            gano = 1 if pl.get("team") == ganador else 0
            registro["ganadas"] += gano
            registro["partidas"].append({"match_id": mid, "start_time": arranque,
                                         "gano": gano})

    cuentas = sorted(por_cuenta)
    rankeadas = [c for c in cuentas if por_cuenta[c]["rankeada"]]
    if args.n and args.n < len(cuentas):
        rng = random.Random(args.semilla)
        if args.preferir_rankeadas:
            semilla_orden = rankeadas[:]
            rng.shuffle(semilla_orden)
            resto = [c for c in cuentas if not por_cuenta[c]["rankeada"]]
            rng.shuffle(resto)
            muestra = (semilla_orden + resto)[:args.n]
        else:
            muestra = rng.sample(cuentas, args.n)
        muestra.sort()
    else:
        muestra = cuentas

    salida = {
        "generado": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "fuente": "data/api_cache/multiheroe/*.json (/v1/matches/metadata)",
        "heroe": "Abrams (hero_id 6)",
        "archivos": len(rutas),
        "archivos_ilegibles": leer_fallidas,
        "partidas_unicas": len(partidas),
        "jugador_partida": jugadores,
        "cuentas_totales": len(cuentas),
        "cuentas_abrams": len(cuentas),
        "cuentas_vistas_en_ranked": len(rankeadas),
        "muestra_vistas_en_ranked": sum(1 for a in muestra if por_cuenta[a]["rankeada"]),
        "semilla_rng": args.semilla,
        "n_muestra": len(muestra),
        "muestra": [
            {"account_id": acc,
             "partidas_abrams": len(por_cuenta[acc]["partidas"]),
             "ganadas_abrams": por_cuenta[acc]["ganadas"],
             "vista_en_ranked": por_cuenta[acc]["rankeada"]}
            for acc in muestra
        ],
    }
    os.makedirs(os.path.dirname(args.salida), exist_ok=True)
    with open(args.salida, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    print(f"partidas únicas: {len(partidas)} · jugador-partida: {jugadores}")
    print(f"cuentas que jugaron Abrams: {len(cuentas)} · vistas en ranked: {len(rankeadas)}")
    print(f"muestra: {len(muestra)} · de ellas vistas en ranked: "
          f"{sum(1 for a in muestra if por_cuenta[a]['rankeada'])}")
    print(f"escrito: {args.salida}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Corpus de Abrams por parche, desde `datos/historico.db` (solo lectura).

Qué costruye y por qué
----------------------
La base `datos/historico.db` (9 731 partidas, 20 parches, ago-2025 → nov-2026) mezcla
tres modos. `StreetBrawl` (580 partidas, 8 jugadores) es el modo que contaminó `lab.db` y
no es comparable: economía y duración distintas. Este corpus deja **solo `game_mode =
Normal`** y exige **12 jugadores** por partida (el formato de 6v6; el filtro es redundante
hoy — las 9 151 partidas Normal tienen 12 — pero queda escrito para que un cambio futuro
del feed no meta partidas a medias sin que nadie lo note).

Una fila = una compra de Abrams. `hero_id = 6` aparece exactamente una vez por partida
(medido: 3 995 partidas de Abrams Normal, 1 por partida), así que `match_id` + `player_slot`
identifican al jugador y `ganador` es el resultado de su equipo.

Columnas (las pedidas + dos llaves)
-----------------------------------
    match_id     llave de agrupación (el bootstrap y los errores estándar agrupan por aquí)
    player_slot  llave del jugador de Abrams
    parche       etiqueta del parche (fecha del título; ver PARCHES-2026-11-18.md)
    badge        average_badge de la partida; NULL si la API no lo trajo
    match_mode   Unranked / Ranked
    net_worth    net worth del jugador en el instante de la compra (`net_worth_at_buy`)
    t            game_time_s de la compra
    item_id      ítem comprado (solo ítems de tienda, filtrados por catálogo)
    ganador      1 si el equipo de Abrams ganó, 0 si no

`match_id` y `player_slot` no son variables de análisis: son llaves. Sin ellas no se puede
agrupar el error estándar por partida, que es obligatorio porque cada partida aporta ~16
compras con **un solo** resultado (las compras de un jugador no son independientes).

Sale:
    datos/corpus_parches.csv.gz          el corpus
    datos/corpus_parches.manifiesto.json conteos, filtros, sha256 y consultas

Uso:
    python3 herramientas/lab/corpus_parches.py
    python3 herramientas/lab/corpus_parches.py --db datos/historico.db --salida /tmp/c.csv.gz
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(RAIZ, "datos", "historico.db")
SALIDA = os.path.join(RAIZ, "datos", "corpus_parches.csv.gz")
MANIFIESTO = os.path.join(RAIZ, "datos", "corpus_parches.manifiesto.json")
ABRAMS = 6
JUGADORES = 12
MODO = "Normal"

CONSULTA = """
SELECT c.match_id, c.player_slot, p.parche, p.badge, p.match_mode,
       c.net_worth, c.t, c.item_id, j.ganador
FROM compras c
JOIN jugadores j ON j.match_id = c.match_id AND j.player_slot = c.player_slot
JOIN partidas  p ON p.match_id = c.match_id
WHERE j.hero_id = :heroe
  AND p.game_mode = :modo
  AND j.ganador IS NOT NULL
  AND c.net_worth IS NOT NULL
  AND p.match_id IN (SELECT match_id FROM jugadores GROUP BY match_id
                     HAVING COUNT(*) = :jugadores)
"""

COLUMNAS = ("match_id", "player_slot", "parche", "badge", "match_mode",
            "net_worth", "t", "item_id", "ganador")


def orden_parche(etiqueta):
    """Clave cronológica del parche: la fecha del título MM-DD-YYYY."""
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})", etiqueta or "")
    if not m:
        return (9999, 99, 99)
    return (int(m.group(3)), int(m.group(1)), int(m.group(2)))


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="Corpus de Abrams Normal por parche")
    ap.add_argument("--db", default=DB)
    ap.add_argument("--salida", default=SALIDA)
    ap.add_argument("--manifiesto", default=MANIFIESTO)
    args = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True)
    filas = con.execute(CONSULTA, {"heroe": ABRAMS, "modo": MODO,
                                   "jugadores": JUGADORES}).fetchall()
    if not filas:
        print("no salió ninguna fila; revisa el filtro", file=sys.stderr)
        return 1

    # ---- controles antes de escribir
    partidas = {r[0] for r in filas}
    parche_de = {r[0]: r[2] for r in filas}
    por_parche = collections.Counter(r[2] for r in filas)
    part_por_parche = collections.Counter(parche_de[mid] for mid in partidas)
    ganadores = {r[8] for r in filas}
    if not ganadores <= {0, 1}:
        print("ganador fuera de {0,1}: %r" % ganadores, file=sys.stderr)
        return 1
    if len(partidas) != len({(r[0], r[1]) for r in filas}):
        print("un match_id con más de un player_slot de Abrams", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(os.path.abspath(args.salida)), exist_ok=True)
    tmp = args.salida + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", newline="", compresslevel=6) as f:
        w = csv.writer(f)
        w.writerow(COLUMNAS)
        w.writerows(filas)
    os.replace(tmp, args.salida)

    parches = sorted(por_parche, key=orden_parche)
    manifiesto = {
        "generado_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "fuente": os.path.relpath(args.db, RAIZ),
        "filtros": {"hero_id": ABRAMS, "game_mode": MODO,
                    "jugadores_por_partida": JUGADORES,
                    "ganador_no_nulo": True, "net_worth_no_nulo": True},
        "consulta": " ".join(CONSULTA.split()),
        "filas": len(filas),
        "partidas": len(partidas),
        "parches": len(parches),
        "compras_por_partida": round(len(filas) / len(partidas), 4),
        "badge_nulo": sum(1 for r in filas if r[3] is None),
        "por_parche": [{"parche": p, "filas": por_parche[p],
                        "partidas": part_por_parche[p]} for p in parches],
        "archivo": os.path.relpath(args.salida, RAIZ),
        "sha256": sha256(args.salida),
        "bytes": os.path.getsize(args.salida),
    }
    with open(args.manifiesto, "w", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=1)

    print("%d filas · %d partidas · %d parches · %.2f compras/partida"
          % (manifiesto["filas"], manifiesto["partidas"], manifiesto["parches"],
             manifiesto["compras_por_partida"]))
    print("badge nulo: %d filas (%.2f %%)"
          % (manifiesto["badge_nulo"],
             100.0 * manifiesto["badge_nulo"] / manifiesto["filas"]))
    print("%-22s %6s %8s" % ("parche", "filas", "partidas"))
    for x in manifiesto["por_parche"]:
        print("%-22s %6d %8d" % (x["parche"], x["filas"], x["partidas"]))
    print("sha256 %s" % manifiesto["sha256"])
    print("-> %s" % args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())

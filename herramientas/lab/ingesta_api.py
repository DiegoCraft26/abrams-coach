#!/usr/bin/env python3
"""Baja partidas reales (con la línea de compras de cada jugador) al laboratorio.

Por qué: `data/replay_cache.json` son 626 partidas de una sola cuenta y de parches
viejos. Con esa muestra todo ensayo sale «sin evidencia» y el laboratorio no sirve.
El endpoint `/v1/matches/metadata` devuelve, por partida y por jugador, cada compra con
`game_time_s` y **`net_worth_at_buy`** — justo el campo que permite comparar ítems entre
jugadores que iban igual de ricos, en vez de comparar promedios que mezclan al que va
ganando con el que va perdiendo.

Lo que guarda: partidas_api, jugadores_api y compras_api (ver `db.py`). Se puede parar
y volver a correr: arranca desde el último match_id guardado.

Uso:
    python3 herramientas/lab/ingesta_api.py --max 2000
    python3 herramientas/lab/ingesta_api.py --parche 1793854800 --max 500
    python3 herramientas/lab/ingesta_api.py --heroes 6 --max 20000 --lote 1000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from herramientas.lab import db  # noqa: E402

BASE = "https://api.deadlock-api.com/v1/matches/metadata"
H = {"User-Agent": "abrams-coach/lab", "Accept": "application/json"}
PARCHE_ACTUAL = 1793854800        # 2026-11-05 05:00 UTC, Minor Update 11-04-2026

ITEMS = os.path.join(RAIZ, "data", "items.json")


def costes():
    with open(ITEMS, encoding="utf-8") as f:
        datos = json.load(f)
    valores = datos.values() if isinstance(datos, dict) else datos
    return {int(v["id"]): v.get("cost") or 0 for v in valores if v.get("id")}


def get(url, intentos=4):
    for i in range(intentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=H),
                                        timeout=180) as r:
                return json.load(r)
        except Exception as e:                                  # noqa: BLE001
            if i == intentos - 1:
                print(f"  fallo: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (i + 1))


def main():
    ap = argparse.ArgumentParser(description="Ingesta masiva desde deadlock-api")
    ap.add_argument("--parche", type=int, default=PARCHE_ACTUAL)
    ap.add_argument("--heroes", default="6")
    ap.add_argument("--max", type=int, default=1000)
    ap.add_argument("--lote", type=int, default=250)
    ap.add_argument("--db", default=db.RUTA)
    args = ap.parse_args()

    con = db.conectar(args.db)
    db.crear_esquema(con)
    coste = costes()
    desde = con.execute("SELECT max(match_id) FROM partidas_api").fetchone()[0] or 0
    print(f"arranca en match_id > {desde} · parche {args.parche} · héroes {args.heroes}")

    traidos = partidas = 0
    while traidos < args.max:
        q = {"hero_ids": args.heroes, "min_unix_timestamp": args.parche,
             "include_player_items": "true", "limit": str(args.lote),
             "order_by": "match_id", "order_direction": "asc",
             "format": "json"}
        if desde:
            q["min_match_id"] = str(desde + 1)
        url = f"{BASE}?{urllib.parse.urlencode(q)}"
        datos = get(url)
        if not datos:
            break
        if not isinstance(datos, list):
            print(f"respuesta inesperada: {list(datos)[:5]}")
            break
        for m in datos:
            mid = int(m.get("match_id") or 0)
            if not mid or mid <= desde:
                continue
            inicio = m.get("start_time") or 0
            dur = m.get("duration_s") or 0
            ganador = m.get("winning_team")
            con.execute("INSERT OR REPLACE INTO partidas_api "
                        "(match_id,start_time,duracion_s,ganador,badge,parche) "
                        "VALUES (?,?,?,?,?,?)",
                        (mid, inicio, dur, ganador, m.get("average_badge"),
                         str(args.parche)))
            for p in (m.get("players") or []):
                slot = p.get("player_slot")
                hero = p.get("hero_id")
                gano = 1 if (ganador is not None and p.get("team") == ganador) else 0
                con.execute("INSERT OR REPLACE INTO jugadores_api "
                            "(match_id,player_slot,hero_id,ganador,build_id) "
                            "VALUES (?,?,?,?,?)",
                            (mid, slot, hero, gano, p.get("hero_build_id")))
                filas = []
                for it in (p.get("items") or []):
                    iid = it.get("item_id")
                    if not iid:
                        continue
                    # El array mezcla compras de tienda con mejoras de habilidad.
                    # Las compras reales traen `upgrade_id = 1`; las habilidades, su
                    # propio id. El filtro fiable es que el id sea un ítem de tienda.
                    if int(iid) not in coste:
                        continue
                    filas.append((it.get("game_time_s") or 0, str(iid),
                                  coste.get(int(iid), 0),
                                  it.get("net_worth_at_buy") or 0,
                                  it.get("sold_time_s") or 0))
                filas.sort(key=lambda f: f[0])
                con.executemany(
                    "INSERT OR REPLACE INTO compras_api (match_id,player_slot,orden,"
                    "t,item_id,coste,net_worth,vendido_t) VALUES (?,?,?,?,?,?,?,?)",
                    [(mid, slot, i + 1, f[0], f[1], f[2], f[3], f[4])
                     for i, f in enumerate(filas)])
            partidas += 1
            desde = max(desde, mid)
            traidos += 1
        con.commit()
        print(f"  {partidas} partidas · último match_id {desde}")
        if len(datos) < args.lote:
            break
        time.sleep(0.4)

    con.commit()
    r = db.resumen(con)
    n_api = con.execute("SELECT count(*) FROM partidas_api").fetchone()[0]
    c_api = con.execute("SELECT count(*) FROM compras_api").fetchone()[0]
    print(f"listo: {n_api} partidas api, {c_api} compras api · total histórico "
          f"{r['partidas']} partidas")
    return 0


if __name__ == "__main__":
    sys.exit(main())

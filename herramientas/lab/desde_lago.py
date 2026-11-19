#!/usr/bin/env python3
"""Reconstruye el laboratorio desde el data lake público, sin gastar cupo de la API.

Por qué existe. Hasta hoy las tablas `*_api` de `datos/lab.db` se llenaban partida a
partida con `/v1/matches/metadata` (~2 peticiones por partida) o con un crawler que
gastaba las 200/hora de `demo/query`. Con 20 500 partidas y 3.8 M de compras eso son
horas de cupo y una petición por partida.

El lake público (`https://data.deadlock-api.com/v1/catalog.ducklake`) expone las mismas
columnas en Parquet y DuckDB las consulta **por HTTP sin descargar el fichero entero**.
Ni cupo, ni claves, ni esperas: se lee lo que haga falta y punto.

Qué reproduce, exactamente:
    partidas_api   match_id, start_time, duracion_s, ganador (Team0/Team1), badge, parche
    jugadores_api  match_id, player_slot, hero_id, ganador (1/0), build_id
    compras_api    match_id, player_slot, orden, t, item_id, coste, net_worth, vendido_t

Diferencias honestas con la ingesta por API:
- `net_worth` por compra no viene en el lake; se toma del muestreo `stats.net_worth`
  en el último instante anterior a la compra (ASOF). El endpoint daba
  `net_worth_at_buy` exacto, así que aquí hay un error de como mucho un intervalo de
  muestreo (≈1 min). Se documenta en la columna, no se disimula.
- Sólo entran ítems de tienda con coste (`data/items.json`), igual que en la ingesta
  original: el array mezcla compras con mejoras de habilidad.

Uso:
    # una hora, para validar contra lab.db
    python3 herramientas/lab/desde_lago.py --desde "2026-11-18 06:00" --hasta "2026-11-18 07:00"

    # tres días completos a la base de trabajo
    python3 herramientas/lab/desde_lago.py --desde 2026-11-16 --dias 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from herramientas.lab import db  # noqa: E402

CATALOGO = "https://data.deadlock-api.com/v1/catalog.ducklake"
ITEMS = os.path.join(RAIZ, "data", "items.json")


def costes() -> dict[int, int]:
    with open(ITEMS, encoding="utf-8") as f:
        datos = json.load(f)
    valores = datos.values() if isinstance(datos, dict) else datos
    return {int(v["id"]): int(v.get("cost") or 0) for v in valores
            if v.get("id") and v.get("shopable") and (v.get("cost") or 0) > 0}


def lago():
    import duckdb
    con = duckdb.connect()
    con.execute("INSTALL ducklake; LOAD ducklake;")
    con.execute(f"ATTACH 'ducklake:{CATALOGO}' AS lago;")
    return con


def ventana(desde: str, hasta: str) -> str:
    return (f"start_time >= TIMESTAMPTZ '{desde}+00' "
            f"AND start_time < TIMESTAMPTZ '{hasta}+00'")


def traer_partidas(lago_con, cond: str) -> list[tuple]:
    return lago_con.execute(f"""
        SELECT match_id, min(start_time), any_value(duration_s),
               any_value(winning_team), any_value(average_badge)
        FROM lago.main.match_player
        WHERE {cond}
        GROUP BY match_id
        ORDER BY match_id
    """).fetchall()


def traer_jugadores(lago_con, cond: str) -> list[tuple]:
    return lago_con.execute(f"""
        SELECT match_id, player_slot, hero_id,
               CASE WHEN team = winning_team THEN 1 ELSE 0 END,
               hero_build_id
        FROM lago.main.match_player
        WHERE {cond}
        ORDER BY match_id, player_slot
    """).fetchall()


def traer_compras(lago_con, cond: str) -> list[tuple]:
    """Compras ordenadas, con el net worth del último muestreo antes de la compra."""
    return lago_con.execute(f"""
        WITH c AS (
            SELECT match_id, player_slot,
                   unnest("items.game_time_s") AS t,
                   unnest("items.item_id")     AS iid,
                   unnest("items.sold_time_s") AS sold
            FROM lago.main.match_player
            WHERE {cond}
        ), s AS (
            SELECT match_id, player_slot,
                   unnest("stats.time_stamp_s") AS ts,
                   unnest("stats.net_worth")    AS nw
            FROM lago.main.match_player
            WHERE {cond}
        )
        SELECT c.match_id, c.player_slot, c.t, c.iid, c.sold,
               coalesce(s.nw, 0) AS nw
        FROM c
        ASOF LEFT JOIN s
          ON c.match_id = s.match_id AND c.player_slot = s.player_slot
         AND c.t >= s.ts
        ORDER BY c.match_id, c.player_slot, c.t
    """).fetchall()


def main() -> int:
    ap = argparse.ArgumentParser(description="lab.db desde el data lake público")
    ap.add_argument("--desde", default="2026-11-18 00:00", help="inicio UTC, 'AAAA-MM-DD HH:MM'")
    ap.add_argument("--hasta", default="", help="fin UTC; si falta, se usa --dias")
    ap.add_argument("--dias", type=int, default=1, help="ventana en días cuando no hay --hasta")
    ap.add_argument("--db", default=os.path.join(RAIZ, "datos", "lab_lago.db"))
    ap.add_argument("--parche", default="", help="etiqueta de parche; por defecto, la fecha de inicio")
    ap.add_argument("--heroe", type=int, default=0,
                    help="sólo partidas con ese héroe (6 = Abrams); 0 = todas")
    ap.add_argument("--match-desde", type=int, default=0, help="match_id mínimo, inclusive")
    ap.add_argument("--match-hasta", type=int, default=0, help="match_id máximo, inclusive")
    ap.add_argument("--vaciar", action="store_true",
                    help="limpia las tres tablas *_api antes de escribir (no toca compras, "
                         "partidas ni ensayos del corpus de replays)")
    args = ap.parse_args()

    desde = args.desde
    hasta = args.hasta
    if not hasta:
        import datetime as dt
        base = dt.datetime.strptime(desde, "%Y-%m-%d %H:%M" if " " in desde else "%Y-%m-%d")
        hasta = (base + dt.timedelta(days=args.dias)).strftime("%Y-%m-%d %H:%M")
    parche = args.parche or desde

    print(f"ventana: {desde} → {hasta} UTC · destino {args.db}")
    t0 = time.time()
    con_lago = lago()
    cond = ventana(desde, hasta)
    if args.match_desde:
        cond += f" AND match_id >= {args.match_desde}"
    if args.match_hasta:
        cond += f" AND match_id <= {args.match_hasta}"
    if args.heroe:
        # El laboratorio es de un héroe: sólo partidas donde aparece (mismo criterio
        # que la ingesta por API, que consultaba con hero_ids).
        cond += (f" AND match_id IN (SELECT match_id FROM lago.main.match_player"
                 f" WHERE {cond} AND hero_id = {args.heroe})")

    partidas = traer_partidas(con_lago, cond)
    print(f"  partidas: {len(partidas):,} ({time.time() - t0:.1f}s)")
    jugadores = traer_jugadores(con_lago, cond)
    print(f"  jugadores: {len(jugadores):,} ({time.time() - t0:.1f}s)")
    compras = traer_compras(con_lago, cond)
    print(f"  compras (antes de filtrar): {len(compras):,} ({time.time() - t0:.1f}s)")

    coste = costes()
    con = db.conectar(args.db)
    db.crear_esquema(con)
    if args.vaciar:
        for tabla in ("compras_api", "jugadores_api", "partidas_api"):
            con.execute(f"DELETE FROM {tabla}")
        con.commit()
        print("  tablas *_api vaciadas")

    con.executemany(
        "INSERT OR REPLACE INTO partidas_api "
        "(match_id,start_time,duracion_s,ganador,badge,parche) VALUES (?,?,?,?,?,?)",
        [(int(m), str(s), int(d or 0), g, b, parche) for m, s, d, g, b in partidas])

    con.executemany(
        "INSERT OR REPLACE INTO jugadores_api "
        "(match_id,player_slot,hero_id,ganador,build_id) VALUES (?,?,?,?,?)",
        [(int(m), int(p), h, int(g), b) for m, p, h, g, b in jugadores])

    orden: dict[tuple[int, int], int] = {}
    filas = []
    saltadas = 0
    for m, p, t, iid, sold, nw in compras:
        if iid is None or int(iid) not in coste:
            saltadas += 1
            continue
        clave = (int(m), int(p))
        orden[clave] = orden.get(clave, 0) + 1
        filas.append((clave[0], clave[1], orden[clave], float(t or 0), str(int(iid)),
                      coste[int(iid)], int(nw or 0), float(sold or 0)))
    con.executemany(
        "INSERT OR REPLACE INTO compras_api "
        "(match_id,player_slot,orden,t,item_id,coste,net_worth,vendido_t) "
        "VALUES (?,?,?,?,?,?,?,?)", filas)
    con.commit()

    print(f"  guardadas: {len(filas):,} compras · {saltadas:,} no eran de tienda")
    print(f"listo en {time.time() - t0:.1f}s → {args.db}")
    for tabla in ("partidas_api", "jugadores_api", "compras_api"):
        n = con.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]
        print(f"  {tabla:<14} {n:>10,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

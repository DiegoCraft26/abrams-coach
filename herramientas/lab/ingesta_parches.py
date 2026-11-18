#!/usr/bin/env python3
"""Ingesta por parche: convierte los historiales de jugador en una serie temporal.

Problema que resuelve: todo el corpus actual (lab.db, 8 300 partidas) es UN parche
(1792033920, 2026-10-15) y una ventana de 2.5 h. Sin una serie por parche no se puede
ver deriva del meta ni «metas rotos históricos».

De dónde salen los match ids: `datos/macro/cache/historial/*.json` (540 historiales de
/v1/players/{id}/match-history). De ahí se deduplica por match_id -> candidatos.json.

Cómo se asigna una partida a un parche (regla implementada):
  1. Se descarga /v1/patches (cache: datos/parch-es/cache/patches.json).
  2. La fecha del parche es la que trae el TÍTULO ("09-29-2026" -> 2026-09-29 00:00 UTC),
     NO `pub_date`. Motivo medido: `pub_date` es la fecha de publicación en el foro y llega
     de 0 a 35 días tarde; tres parches (08-12, 08-22, 09-16) comparten pub_date 2026-09-16
     con 33 s de diferencia (backfill del feed). El título coincide con
     /v1/patches/big-days (fecha real de despliegue) en 6/6 parches verificables.
  3. Una partida pertenece al parche p si start_time ∈ [fecha_p, fecha_p+1).
     Las anteriores al primer corte quedan como «sin parche» y no se muestrean.
  4. Se guardan las dos etiquetas: `parche` (título) y `parche_feed` (pub_date), para poder
     re-agrupar sin volver a descargar.

Muestreo: hasta --muestra partidas por parche (las más recientes), solo parches con
>= --min-cand candidatas, con tope global --tope.

Descarga: metadata en lotes de 1000 match_ids, con caché gzip por lote en
datos/parch-es/cache/lotes/<sha1>.json.gz. Reanudable: si el lote ya está en caché no se
vuelve a pedir. Ritmo: 1 petición cada 4 s (el endpoint declara 30 req/min por IP).

Uso:
    python3 herramientas/lab/ingesta_parches.py --plan          # solo calcula y escribe plan
    python3 herramientas/lab/ingesta_parches.py                 # baja e ingiere
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PARCHES = os.path.join(RAIZ, "datos", "parch-es")
CACHE = os.path.join(PARCHES, "cache")
LOTES = os.path.join(CACHE, "lotes")
DB = os.path.join(RAIZ, "datos", "historico.db")
CANDIDATOS = os.path.join(PARCHES, "candidatos.json")
PATCHES_JSON = os.path.join(CACHE, "patches.json")
ITEMS = os.path.join(RAIZ, "data", "items.json")

BASE = "https://api.deadlock-api.com/v1/matches/metadata"
H = {"User-Agent": "abrams-coach/lab-parches", "Accept": "application/json",
     "Accept-Encoding": "gzip"}

INTERVALO_S = 4.0          # 15/min; el endpoint declara 30/min por IP
MAX_INTENTOS = 4

ESQUEMA = """
CREATE TABLE IF NOT EXISTS partidas (
    match_id    INTEGER PRIMARY KEY,
    start_time  INTEGER NOT NULL,
    duracion_s  INTEGER,
    parche      TEXT,             -- etiqueta por fecha del título del parche
    ganador     INTEGER,          -- 0 / 1
    parche_feed TEXT,             -- etiqueta por pub_date de /v1/patches (para cotejo)
    game_mode   TEXT,
    match_mode  TEXT,
    badge       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_partidas_parche ON partidas (parche, start_time);

CREATE TABLE IF NOT EXISTS jugadores (
    match_id    INTEGER NOT NULL,
    player_slot INTEGER NOT NULL,
    hero_id     INTEGER,
    ganador     INTEGER,
    team        INTEGER,
    net_worth   INTEGER,
    PRIMARY KEY (match_id, player_slot)
);
CREATE INDEX IF NOT EXISTS idx_jugadores_heroe ON jugadores (hero_id, match_id);

CREATE TABLE IF NOT EXISTS compras (
    match_id    INTEGER NOT NULL,
    player_slot INTEGER NOT NULL,
    t           REAL NOT NULL,     -- game_time_s
    item_id     INTEGER NOT NULL,
    orden       INTEGER NOT NULL,  -- 1..n en orden de compra
    net_worth   INTEGER,
    PRIMARY KEY (match_id, player_slot, orden)
);
CREATE INDEX IF NOT EXISTS idx_compras_item ON compras (item_id, match_id);
CREATE INDEX IF NOT EXISTS idx_compras_t ON compras (match_id, t);

CREATE TABLE IF NOT EXISTS lotes (
    hash     TEXT PRIMARY KEY,
    n_ids    INTEGER,
    n_part   INTEGER,
    bytes    INTEGER,
    ts       TEXT
);
"""


def log(msg):
    print(msg, flush=True)


def epoch(s):
    return int(dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
               .replace(tzinfo=dt.timezone.utc).timestamp())


def fecha_titulo(titulo):
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})", titulo or "")
    if not m:
        return None
    return int(dt.datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)),
                           tzinfo=dt.timezone.utc).timestamp())


def parches():
    with open(PATCHES_JSON, encoding="utf-8") as f:
        datos = json.load(f)
    filas = []
    for p in datos:
        t = fecha_titulo(p.get("title"))
        filas.append({"titulo": p["title"], "inicio": t,
                      "pub": epoch(p["pub_date"]) if p.get("pub_date") else None})
    filas = [f for f in filas if f["inicio"]]
    filas.sort(key=lambda f: f["inicio"])
    for i, f in enumerate(filas):
        f["fin"] = filas[i + 1]["inicio"] if i + 1 < len(filas) else None
    return filas


def plan(parches_l, muestra, min_cand, tope, orden):
    with open(CANDIDATOS, encoding="utf-8") as f:
        cand = json.load(f)
    cubos = {p["titulo"]: [] for p in parches_l}
    fuera = 0
    for c in cand:
        t = c["start_time"]
        if t < parches_l[0]["inicio"]:
            fuera += 1
            continue
        for p in parches_l:
            if p["fin"] is None or t < p["fin"]:
                cubos[p["titulo"]].append(c)
                break
    # más recientes primero para llegar al presupuesto con los parches nuevos
    lista = parches_l if orden == "asc" else list(reversed(parches_l))
    elegidos, total = [], 0
    for p in lista:
        cs = sorted(cubos[p["titulo"]], key=lambda c: -c["start_time"])
        p["candidatas"] = len(cs)
        p["muestra"] = 0
        if len(cs) < min_cand:
            p["motivo"] = "menos de %d candidatas" % min_cand
            continue
        n = min(muestra, len(cs), tope - total)
        if n <= 0:
            p["motivo"] = "presupuesto agotado"
            continue
        trozo = cs[:n]
        con_st = {p["titulo"]: {c["match_id"]: c["start_time"] for c in trozo}}
        elegidos.append({"parche": p["titulo"], "ids": [c["match_id"] for c in trozo],
                         "st": con_st[p["titulo"]], "inicio": p["inicio"],
                         "fin": p["fin"]})
        p["muestra"] = n
        total += n
    meta = {"generado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "regla": "start_time en [fecha del titulo del parche, fecha del siguiente)",
            "muestra_por_parche": muestra, "min_candidatas": min_cand,
            "tope": tope, "total_elegido": total,
            "sin_parche": {"n": fuera, "hasta": parches_l[0]["inicio"]},
            "parches": [{k: p.get(k) for k in
                         ("titulo", "inicio", "fin", "pub", "candidatas", "muestra", "motivo")}
                        for p in parches_l]}
    with open(os.path.join(PARCHES, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return elegidos, meta


def esperar_ritmo(ruta):
    """Ventana móvil persistente: no más de 15 peticiones/min ni <4 s entre una y otra."""
    marcas = []
    try:
        with open(ruta, encoding="utf-8") as f:
            marcas = [m for m in json.load(f).get("marcas", []) if time.time() - m < 65]
    except (OSError, ValueError):
        marcas = []
    ahora = time.time()
    if marcas:
        pausa = INTERVALO_S - (ahora - marcas[-1])
        if pausa > 0:
            time.sleep(pausa)
    marcas = [m for m in marcas if time.time() - m < 65]
    marcas.append(time.time())
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"marcas": marcas[-40:]}, f)


def pedir(ids, ruta_pausa):
    url = BASE + "?" + urllib.parse.urlencode({
        "match_ids": ",".join(str(i) for i in ids),
        "include_info": "true", "include_player_info": "true",
        "include_player_items": "true", "format": "json"})
    for intento in range(MAX_INTENTOS):
        esperar_ritmo(ruta_pausa)
        try:
            req = urllib.request.Request(url, headers=H)
            with urllib.request.urlopen(req, timeout=300) as r:
                crudo = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    crudo = gzip.decompress(crudo)
                return json.loads(crudo), len(crudo)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # la API responde 404 cuando NINGUNO de los match_ids está en su índice
                # de metadata; no es un error transitorio y no se reintenta
                return [], 0
            espera = int(e.headers.get("Retry-After") or 0) or (5 * (intento + 1))
            log("  HTTP %s; espero %ss" % (e.code, espera))
            time.sleep(espera)
        except Exception as e:                       # noqa: BLE001
            log("  fallo (%s/%s): %s" % (intento + 1, MAX_INTENTOS, e))
            time.sleep(4 * (intento + 1))
    return None, 0


def escribir_gzip(ruta, dato):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(dato, f, separators=(",", ":"))
    os.replace(tmp, ruta)


def leer_gzip(ruta):
    with gzip.open(ruta, "rt", encoding="utf-8") as f:
        return json.load(f)


def costes():
    with open(ITEMS, encoding="utf-8") as f:
        datos = json.load(f)
    vals = datos.values() if isinstance(datos, dict) else datos
    return {int(v["id"]): v.get("cost") or 0
            for v in vals if v.get("id") and (v.get("cost") or 0) > 0}


def ingerir(con, metas, coste, etiqueta):
    """`etiqueta`: match_id -> (parche, parche_feed, start_time)."""
    pat = 0
    for m in metas:
        mid = int(m.get("match_id") or 0)
        if not mid:
            continue
        g = m.get("winning_team")
        ganador = None
        if isinstance(g, str) and g.lower().startswith("team"):
            ganador = int(g[-1])
        elif isinstance(g, int):
            ganador = g
        parche, parche_feed, inicio = etiqueta.get(mid, (None, None, 0))
        con.execute(
            "INSERT OR REPLACE INTO partidas (match_id,start_time,duracion_s,parche,"
            "ganador,parche_feed,game_mode,match_mode,badge) VALUES (?,?,?,?,?,?,?,?,?)",
            (mid, inicio, m.get("duration_s"), parche, ganador, parche_feed,
             m.get("game_mode"), m.get("match_mode"), m.get("average_badge")))
        for p in (m.get("players") or []):
            slot = p.get("player_slot")
            team = p.get("team")
            t_idx = None
            if isinstance(team, str) and team.lower().startswith("team"):
                t_idx = int(team[-1])
            gano = 1 if (t_idx is not None and ganador is not None and t_idx == ganador) else 0
            con.execute(
                "INSERT OR REPLACE INTO jugadores (match_id,player_slot,hero_id,ganador,"
                "team,net_worth) VALUES (?,?,?,?,?,?)",
                (mid, slot, p.get("hero_id"), gano, t_idx, p.get("net_worth")))
            filas = []
            for it in (p.get("items") or []):
                try:
                    iid = int(it.get("item_id"))
                except (TypeError, ValueError):
                    continue
                if iid not in coste:
                    continue                      # mejora de habilidad, no compra
                filas.append((float(it.get("game_time_s") or 0), iid,
                              it.get("net_worth_at_buy")))
            filas.sort(key=lambda f: f[0])
            if filas:
                con.executemany(
                    "INSERT OR REPLACE INTO compras (match_id,player_slot,t,item_id,orden,"
                    "net_worth) VALUES (?,?,?,?,?,?)",
                    [(mid, slot, f[0], f[1], i + 1, f[2]) for i, f in enumerate(filas)])
        pat += 1
    return pat


def main():
    ap = argparse.ArgumentParser(description="Ingesta por parche desde historiales")
    ap.add_argument("--muestra", type=int, default=500)
    ap.add_argument("--min-cand", type=int, default=500)
    ap.add_argument("--tope", type=int, default=10000)
    ap.add_argument("--lote", type=int, default=1000)
    ap.add_argument("--orden", default="desc", choices=["asc", "desc"])
    ap.add_argument("--plan", action="store_true", help="solo calcula el plan")
    ap.add_argument("--db", default=DB)
    args = ap.parse_args()

    os.makedirs(LOTES, exist_ok=True)
    pl, meta = plan(parches(), args.muestra, args.min_cand, args.tope, args.orden)
    log("plan: %d parches, %d partidas elegidas (tope %d)"
        % (len(meta["parches"]), meta["total_elegido"], args.tope))
    for p in meta["parches"]:
        log("  %-24s cand %6d  muestra %4d %s"
            % (p["titulo"], p["candidatas"], p["muestra"], p.get("motivo") or ""))
    if args.plan or not pl:
        return 0

    coste = costes()
    con = sqlite3.connect(args.db)
    con.executescript(ESQUEMA)
    con.commit()

    pausa = os.path.join(PARCHES, "pausa.json")
    feed = {p["titulo"]: (dt.datetime.fromtimestamp(p["pub"], dt.timezone.utc)
                          .strftime("%Y-%m-%d") if p.get("pub") else None)
            for p in meta["parches"]}
    etiqueta = {}
    todos = []
    for trozo in pl:
        for mid in trozo["ids"]:
            etiqueta[int(mid)] = (trozo["parche"], feed.get(trozo["parche"]),
                                  trozo["st"].get(int(mid), 0))
            todos.append(mid)
    pendientes = [todos[i:i + args.lote] for i in range(0, len(todos), args.lote)]

    hechos = con.execute("SELECT count(*) FROM lotes").fetchone()[0]
    log("lotes: %d por procesar (caché ya tiene %d registrados en db)"
        % (len(pendientes), hechos))
    for k, ids in enumerate(pendientes, 1):
        h = hashlib.sha1(",".join(map(str, ids)).encode()).hexdigest()[:16]
        ruta = os.path.join(LOTES, h + ".json.gz")
        t0 = time.time()
        if os.path.exists(ruta):
            metas = leer_gzip(ruta)
            fuente = "caché"
        else:
            metas, _ = pedir(ids, pausa)
            if metas is None:
                log("  lote %s FALLÓ; se reintenta en otra corrida" % h)
                continue
            escribir_gzip(ruta, metas)
            fuente = "red"
        n = ingerir(con, metas, coste, etiqueta)
        con.execute("INSERT OR REPLACE INTO lotes (hash,n_ids,n_part,bytes,ts) "
                    "VALUES (?,?,?,?,?)",
                    (h, len(ids), n, os.path.getsize(ruta),
                     dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")))
        con.commit()
        log("  %2d/%d %s %s %4d/%d partidas  %.1fs"
            % (k, len(pendientes), h, fuente, n, len(ids), time.time() - t0))

    tot = con.execute("SELECT count(*) FROM partidas").fetchone()[0]
    jug = con.execute("SELECT count(*) FROM jugadores").fetchone()[0]
    com = con.execute("SELECT count(*) FROM compras").fetchone()[0]
    log("total: %d partidas, %d jugadores, %d compras · %s"
        % (tot, jug, com, args.db))
    return 0




if __name__ == "__main__":
    sys.exit(main())

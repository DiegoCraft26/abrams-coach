#!/usr/bin/env python3
"""Mide las partidas del dueño contra el benchmark de Abrams en `datos/lab.db`.

Entrada:
  - ids de partida (por defecto `/tmp/mis_con_demo.json`);
  - `.cuenta` (account_id del dueño; no se imprime en el JSON de salida);
  - `salida/cache_meta/<match>.json`  metadata de `/v1/matches/{id}/metadata`;
  - `salida/demos_cache/<match>__todo.ndjson` extracción del demo (`consulta.py`).

Qué saca por partida (todo medido, nada supuesto):
  - slot del lobby desde el metadata (cuenta -> player_slot) y mapeo al slot de
    evento del demo (`purchaser_player_slot = entity_index - 1`);
  - compras del demo con el reloj corregido por pausas:
        segundos = (tick - pausados(tick))/64 - preambulo
    donde `preambulo` NO se asume: se calibra emparejando las compras del demo con
    los `items` del metadata (mismo item_id, en orden) y tomando la mediana del
    desfase; los pares que se alejan >5 s se cuentan como emparejamiento dudoso;
  - oro del jugador en cada compra (`CurrencyChangedEvent`, `currency_type=0`);
  - muertes del metadata (`death_details[].game_time_s`), antes del minuto 10 y total.

Benchmark: mismo cálculo sobre `compras_api` (t, item, coste) para las partidas
completas de 12 jugadores con Abrams (`jugadores_api.hero_id=6`), separadas por
`ganador`. Lo que el benchmark no tiene (muertes, participación) se marca aparte.

Uso:
    python3 herramientas/demos/personal.py --json informes/lab/personal-demos.json
    python3 herramientas/demos/personal.py --matches 139556523 --sin-benchmark
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.request
import statistics
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CUENTA = RAIZ / ".cuenta"
ITEMS = RAIZ / "data" / "items.json"
LAB = RAIZ / "datos" / "lab.db"
CACHE_META = RAIZ / "salida" / "cache_meta"
CACHE_DEMO = RAIZ / "salida" / "demos_cache"
IDS = Path("/tmp/mis_con_demo.json")
TPS = 64
HEROE_ABRAMS = 6


# ------------------------------------------------------------------ descarga

def bajar_metadata(match: int, forzar: bool = False) -> str:
    """Descarga `/v1/matches/{id}/metadata` a la caché si falta. Devuelve qué hizo."""
    ruta = CACHE_META / f"{match}.json"
    if ruta.exists() and not forzar:
        return "caché"
    url = f"https://api.deadlock-api.com/v1/matches/{match}/metadata"
    for intento in range(3):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": "abrams-coach/lab-demos"}),
                    timeout=90) as r:
                datos = json.load(r)
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(json.dumps(datos), encoding="utf-8")
            return "ok"
        except Exception as e:                                  # noqa: BLE001
            if intento == 2:
                return f"fallo: {e}"
            __import__("time").sleep(2 * (intento + 1))
    return "fallo"


# ------------------------------------------------------------------ utilidades

def leer_rows(ruta: Path) -> list[dict]:
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(linea) for linea in f if linea.strip()]


def decodificar_slot(texto: str | None) -> int | None:
    """`m_unLobbyPlayerSlot` llega como u64 LE: 16 hex o 8 bytes crudos."""
    if not texto:
        return None
    limpio = texto.strip()
    if len(limpio) == 16 and all(c in "0123456789abcdefABCDEF" for c in limpio):
        return int.from_bytes(bytes.fromhex(limpio), "little")
    crudo = texto.encode("utf-8", "surrogateescape")[:8]
    if len(crudo) < 8:
        return None
    return int.from_bytes(crudo, "little")


def catalogo() -> dict[int, dict]:
    crudo = json.loads(ITEMS.read_text(encoding="utf-8"))
    valores = crudo.values() if isinstance(crudo, dict) else crudo
    return {int(v["id"]): {"nombre": v.get("name") or str(v["id"]),
                           "coste": int(v.get("cost") or 0),
                           "tier": int(v.get("item_tier") or 0)}
            for v in valores if v.get("id")}


# --------------------------------------------------------------- el demo crudo

def partir(rows: list[dict]) -> tuple[dict, dict, list[dict], list[tuple[int, int]]]:
    mapa, moneda, compras = {}, defaultdict(list), []
    pausas: list[tuple[int, int]] = []
    for r in rows:
        tag = r.get("tag")
        if tag == "pausa":
            pausas.append((int(r["t"]), int(r["a"] or 0)))
        elif tag == "ctrl":
            entidad = int(r["a"])
            mapa[entidad] = {"slot_lobby": decodificar_slot(r.get("c")),
                             "slot_evento": entidad - 1,
                             "steam_id": int(r["b"]) if r.get("b") else 0,
                             "nombre": r.get("d") or ""}
        elif tag == "cur":
            moneda[(int(r["a"]), int(r["b"]))].append(
                (int(r["t"]), int(r["c"] or 0), int(r["d"] or 0)))
        elif tag == "ab":
            compras.append({"tick": int(r["t"]), "slot": int(r["a"]),
                            "item": int(r["b"]), "cambio": int(r["c"] or 0)})
    for fila in moneda.values():
        fila.sort()
    pausas.sort()
    return mapa, moneda, compras, pausas


def reloj(pausas: list[tuple[int, int]], tick: int) -> float:
    """Segundos de partida del tick, descontando las pausas y sin preámbulo."""
    pausado = 0
    for inicio, acumulado in pausas:
        if tick < inicio:
            break
        pausado = acumulado
    return (tick - pausado) / TPS


def calibrar(compras: list[dict], items_meta: list[dict]) -> dict:
    """Desfase demo<->reloj de partida, medido con los ítems del metadata.

    El metadata da `game_time_s` entero por ítem; el demo da el tick. Se empareja
    por `item_id` en orden y la mediana del desfase es el preámbulo.
    """
    cola: dict[int, list[float]] = defaultdict(list)
    for c in compras:
        cola[c["item"]].append(c["seg_crudo"])
    desfases = []
    for it in sorted(items_meta, key=lambda x: x[0]):
        t_meta, item_id = it[0], it[1]
        if cola.get(item_id):
            desfases.append(cola[item_id].pop(0) - float(t_meta))
    if not desfases:
        return {"preambulo": 0.0, "pares": 0, "dudosos": 0, "mediana": None}
    centro = statistics.median(desfases)
    dudosos = sum(1 for x in desfases if abs(x - centro) > 5.0)
    return {"preambulo": round(centro, 2), "pares": len(desfases),
            "dudosos": dudosos, "mediana": round(centro, 2)}


def oro_en(moneda: dict, slot: int, tick: int) -> int | None:
    mejor = None
    for t, _delta, nuevo in moneda.get((slot, 0), []):
        if t > tick:
            break
        mejor = nuevo
    return mejor


def validar_oro(moneda: dict, slot: int, compras: list[dict]) -> dict:
    """¿El `userid` de la moneda es el slot del evento? Se comprueba con el coste.

    Cada compra debería tener, en el mismo tick o ±0,6 s, un cambio de oro negativo
    de tamaño entre −coste y −10 % del coste (a veces se paga menos porque se
    consumen componentes que ya tenías). El porcentaje que cuadra es la evidencia
    del mapeo `userid` de `CurrencyChangedEvent` = slot del evento.
    """
    fila = moneda.get((slot, 0), [])
    cuadran = 0
    for c in compras:
        if not c.get("coste"):
            continue
        for t, delta, _nuevo in fila:
            if t < c["tick"] - 40:
                continue
            if t > c["tick"] + 40:
                break
            if -c["coste"] <= delta <= -0.1 * c["coste"]:
                cuadran += 1
                break
    validas = [c for c in compras if c.get("coste")]
    return {"compras": len(validas), "cuadran": cuadran,
            "pct": round(100 * cuadran / len(validas), 1) if validas else None}


# ------------------------------------------------------------------- métricas

def metricas_partida(segundos: list[float], costes: list[int],
                     oro_serie: list[tuple[float, int, int]], muertes: list[int],
                     duracion_s: int | None) -> dict:
    """Métricas comunes demo/benchmark. `oro_serie` = (seg, delta, new_value)."""
    salida = {"items": len(segundos)}
    primera = lambda umbral: next((t / 60 for t, c in zip(segundos, costes)
                                  if c == umbral), None)
    salida["min6400"] = primera(6400)
    salida["min3200"] = primera(3200)
    salida["items20"] = sum(1 for t in segundos if t <= 1200)
    salida["inv10"] = sum(c for t, c in zip(segundos, costes) if t <= 600)
    salida["inv20"] = sum(c for t, c in zip(segundos, costes) if t <= 1200)
    for minuto in (10, 20):
        corte = minuto * 60
        saldo = None
        neto = 0
        for t, delta, nuevo in oro_serie:
            if t > corte:
                break
            saldo = nuevo
            if delta > 0:
                neto += delta
        salida[f"oro{minuto}"] = saldo
        salida[f"neto{minuto}"] = neto if oro_serie else None
    salida["muertes10"] = sum(1 for m in muertes if m <= 600) if muertes else None
    salida["muertes"] = len(muertes) if muertes else None
    salida["duracion_s"] = duracion_s
    return salida


def por_partida(match: int, items: dict[int, dict]) -> dict:
    """Lee metadata + demo de una partida y devuelve su fila medida."""
    ruta_meta = CACHE_META / f"{match}.json"
    ruta_demo = CACHE_DEMO / f"{match}__todo.ndjson"
    fila: dict = {"match": match, "fuente": [], "no_medible": []}

    if not ruta_meta.exists():
        fila["no_medible"].append("metadata 404/ausente")
        return fila
    cuenta = int(CUENTA.read_text().strip())
    meta = json.loads(ruta_meta.read_text(encoding="utf-8")).get("match_info") or {}
    jugadores = meta.get("players") or []
    yo = next((p for p in jugadores if int(p.get("account_id") or 0) == cuenta), None)
    if yo is None:
        fila["no_medible"].append("la cuenta no aparece en el metadata")
        return fila

    fila.update({
        "slot": int(yo["player_slot"]),
        "heroe": int(yo.get("hero_id") or 0),
        "equipo": yo.get("team"),
        "gane": int(yo.get("team") == meta.get("winning_team")),
        "duracion_s": int(meta.get("duration_s") or 0),
        "kills": int(yo.get("kills") or 0),
        "deaths": int(yo.get("deaths") or 0),
        "assists": int(yo.get("assists") or 0),
        "net_worth": int(yo.get("net_worth") or 0),
        "parche": meta.get("start_time"),
    })
    muertes = sorted(int(d["game_time_s"]) for d in (yo.get("death_details") or []))
    fila["muertes_s"] = muertes
    todos_meta = sorted((int(i["game_time_s"]), int(i["item_id"]))
                        for i in (yo.get("items") or []))
    # el metadata lista también ids que no son artículos de tienda (se repiten 4-5
    # veces en la misma partida y no están en data/items.json): no son compras
    items_meta = [x for x in todos_meta if x[1] in items]
    fila["items_meta"] = len(items_meta)
    fila["items_meta_fuera_catalogo"] = len(todos_meta) - len(items_meta)
    # net worth del metadata en los cortes de 180 s, para contrastar
    stats = {int(s["time_stamp_s"]): int(s.get("net_worth") or 0)
             for s in (yo.get("stats") or []) if s.get("time_stamp_s") is not None}

    def nw_interp(t: int):
        claves = sorted(stats)
        if not claves:
            return None
        previo = [k for k in claves if k <= t]
        if not previo:
            return None
        if previo[-1] == t or previo[-1] == claves[-1]:
            return stats[previo[-1]]
        siguiente = claves[claves.index(previo[-1]) + 1]
        a, b = previo[-1], siguiente
        peso = (t - a) / (b - a)
        return round(stats[a] + (stats[b] - stats[a]) * peso)

    fila["neto_meta"] = {"600": nw_interp(600), "1200": nw_interp(1200)}

    if not ruta_demo.exists():
        fila["fuente"].append("metadata")
        fila["no_medible"].append("demo no descargada (404/cola): compras y oro sin medir")
        dur = fila["duracion_s"] or None
        fila["participacion"] = round((fila["kills"] + fila["assists"]) /
                                      (dur / 60), 2) if dur else None
        fila["muertes10"] = sum(1 for m in muertes if m <= 600)
        fila["muertes"] = len(muertes)
        fila["items20"] = None
        return fila

    mapa, moneda, compras, pausas = partir(leer_rows(ruta_demo))
    entidad = next((e for e, m in mapa.items() if m["slot_lobby"] == fila["slot"]), None)
    if entidad is None:
        fila["no_medible"].append("el slot del metadata no aparece en el demo")
        return fila
    slot_ev = entidad - 1
    fila["slot_evento"] = slot_ev
    fila["fuente"].append("demo")

    mias = [c for c in compras if c["slot"] == slot_ev and c["cambio"] == 0]
    mias.sort(key=lambda c: c["tick"])
    for c in mias:
        c["seg_crudo"] = reloj(pausas, c["tick"])
        c["coste"] = items.get(c["item"], {}).get("coste", 0)
        c["nombre"] = items.get(c["item"], {}).get("nombre", str(c["item"]))
    if not mias:
        fila["no_medible"].append("el demo no trae compras de este slot")
        return fila

    cal = calibrar(mias, items_meta)
    fila["calibracion"] = cal
    pre = cal["preambulo"] if cal["pares"] >= 3 else 0.0
    for c in mias:
        c["seg"] = c["seg_crudo"] - pre
    # las pausas que caen después del último evento no se notan aquí, pero sí en la
    # duración: se comprueba con el reloj de la partida.
    todas = leer_rows(ruta_demo)
    ultimo = max(int(r["t"]) for r in todas if r.get("t"))
    residuo = reloj(pausas, int(ultimo)) - pre - fila["duracion_s"]
    fila["control_duracion_s"] = round(residuo, 1)

    fila["validacion_oro"] = validar_oro(moneda, slot_ev, mias)
    serie = [(reloj(pausas, t) - pre, d, n) for t, d, n in moneda.get((slot_ev, 0), [])]
    for c in mias:
        c["oro_antes"] = oro_en(moneda, slot_ev, c["tick"] - 1)
        c["oro_despues"] = oro_en(moneda, slot_ev, c["tick"] + 3)
    fila["compras"] = [{"t": round(c["seg"], 1), "min": round(c["seg"] / 60, 2),
                        "item": c["item"], "nombre": c["nombre"],
                        "coste": c["coste"], "oro_antes": c["oro_antes"],
                        "oro_despues": c["oro_despues"]} for c in mias]
    fila["pausas"] = pausas
    fila["segundos_pausados"] = (pausas[-1][1] / TPS if pausas else 0.0)

    met = metricas_partida([c["seg"] for c in mias], [c["coste"] for c in mias],
                           serie, muertes, fila["duracion_s"] or None)
    fila.update(met)
    dur = fila["duracion_s"] or None
    fila["participacion"] = round((fila["kills"] + fila["assists"]) / (dur / 60), 2) if dur else None
    # recall del demo contra la lista de ítems del metadata (evidencia de cobertura)
    fila["recall_meta"] = round(100 * len(mias) / len(items_meta), 1) if items_meta else None
    return fila


# ------------------------------------------------------------------ benchmark

def benchmark(heroe: int = HEROE_ABRAMS, solo_12: bool = True) -> dict:
    con = sqlite3.connect(f"file:{LAB}?mode=ro", uri=True)
    filtro12 = ("AND c.match_id IN (SELECT match_id FROM jugadores_api "
                "GROUP BY match_id HAVING count(*) = 12)") if solo_12 else ""
    q = f"""SELECT c.match_id, c.orden, c.t, c.coste, c.net_worth, j.ganador
            FROM compras_api c JOIN jugadores_api j USING(match_id, player_slot)
            WHERE j.hero_id = {int(heroe)} {filtro12}
            ORDER BY c.match_id, c.orden"""
    partidas: dict[int, dict] = {}
    for match, orden, t, coste, nw, gane in con.execute(q):
        p = partidas.setdefault(match, {"gane": int(gane or 0), "t": [], "coste": [],
                                        "nw": []})
        p["t"].append(float(t))
        p["coste"].append(int(coste or 0))
        p["nw"].append(int(nw or 0))
    con.close()

    filas = []
    for match, p in partidas.items():
        seg = p["t"]
        met = metricas_partida(seg, p["coste"], [(t, 0, n) for t, n in zip(seg, p["nw"])],
                               [], None)
        for clave in ("oro10", "oro20", "neto10", "neto20", "muertes10", "muertes"):
            met.pop(clave, None)
        met["items"] = len(seg)
        # net_worth del último registro antes del corte (el metadata del corpus no
        # guarda la curva, solo el valor en cada compra)
        for minuto in (10, 20):
            corte = minuto * 60
            previos = [(t, n) for t, n in zip(seg, p["nw"]) if t <= corte]
            met[f"nw{minuto}"] = previos[-1][1] if previos else None
            met[f"nw{minuto}_frescura"] = round(corte - previos[-1][0], 1) if previos else None
        met["gane"] = p["gane"]
        met["match"] = match
        filas.append(met)
    return {"n": len(filas), "filas": filas, "solo_12_jugadores": solo_12,
            "heroe": int(heroe)}


# ------------------------------------------------------------------ resumen

# `nw10`/`nw20` del corpus NO entran: `net_worth_at_buy` es la muestra de 180 s
# anterior a la compra (verificado con 131553926: 13099 en la base contra 18938 del
# metadata en el corte de 20 min), así que no es comparable con el neto exacto del demo.
CLAVES = ("min6400", "min3200", "items20", "oro10", "oro20", "neto10", "neto20",
          "inv10", "inv20", "muertes10", "muertes", "participacion")


def mediana(valores: list) -> float | None:
    limpios = [v for v in valores if isinstance(v, (int, float))]
    return round(statistics.median(limpios), 2) if limpios else None


def resumen(mias: list[dict], bench: list[dict]) -> dict:
    def grupo(filas, clave):
        return {etiqueta: [f.get(clave) for f in filas if f.get("gane") == valor]
                for etiqueta, valor in (("ganadas", 1), ("perdidas", 0))}
    salida = {"mias": {"n": len(mias)}, "benchmark": {"n": len(bench)}}
    pares_neto = [(f["neto20"], f["neto_meta"]["1200"]) for f in mias
                  if f.get("neto20") and f.get("neto_meta", {}).get("1200")]
    if pares_neto:
        errores = [abs(a - b) / b for a, b in pares_neto]
        salida["validacion_neto20"] = {
            "n": len(errores),
            "error_medio_pct": round(100 * statistics.mean(errores), 1),
            "error_max_pct": round(100 * max(errores), 1),
        }
    val = [f["validacion_oro"] for f in mias if f.get("validacion_oro")]
    if val:
        salida["validacion_oro"] = {
            "compras": sum(v["compras"] for v in val),
            "cuadran": sum(v["cuadran"] for v in val),
            "pct": round(100 * sum(v["cuadran"] for v in val)
                         / max(1, sum(v["compras"] for v in val)), 1),
        }
    cal = [f["calibracion"] for f in mias if f.get("calibracion")]
    if cal:
        salida["calibracion"] = {
            "pares": sum(c["pares"] for c in cal),
            "dudosos": sum(c["dudosos"] for c in cal),
            "preambulos": sorted({c["preambulo"] for c in cal}),
        }
    for nombre, filas in (("mias", mias), ("benchmark", bench)):
        for clave in CLAVES:
            if not any(clave in f for f in filas):
                continue
            g = grupo(filas, clave)
            salida[nombre][clave] = {
                "todas": mediana([f.get(clave) for f in filas]),
                "ganadas": mediana(g["ganadas"]),
                "perdidas": mediana(g["perdidas"]),
                "n_ganadas": len([v for v in g["ganadas"] if isinstance(v, (int, float))]),
                "n_perdidas": len([v for v in g["perdidas"] if isinstance(v, (int, float))]),
            }
    return salida


def pruebas(mias: list[dict], semilla: int = 0, remuestreos: int = 20000) -> dict:
    """Diferencia ganadas/perdidas con prueba de permutación (media, dos colas)."""
    import random
    rng = random.Random(semilla)
    salida = {}
    for clave in ("min6400", "min3200", "items20", "inv20", "oro20", "neto20",
                  "muertes10", "muertes", "participacion"):
        gan = [f[clave] for f in mias if f.get("gane") and isinstance(f.get(clave), (int, float))]
        per = [f[clave] for f in mias if not f.get("gane") and isinstance(f.get(clave), (int, float))]
        if len(gan) < 4 or len(per) < 4:
            continue
        observado = statistics.mean(gan) - statistics.mean(per)
        juntos = gan + per
        extremos = 0
        for _ in range(remuestreos):
            rng.shuffle(juntos)
            d = statistics.mean(juntos[:len(gan)]) - statistics.mean(juntos[len(gan):])
            if abs(d) >= abs(observado):
                extremos += 1
        salida[clave] = {"media_ganadas": round(statistics.mean(gan), 2),
                         "media_perdidas": round(statistics.mean(per), 2),
                         "delta": round(observado, 2), "n": [len(gan), len(per)],
                         "p": round(extremos / remuestreos, 3)}
    return salida


def reglas(mias: list[dict]) -> list[dict]:
    """Reglas candidatas: umbral, cuántas partidas lo cumplen y tasa de victoria."""
    candidatas = [
        ("min3200", "<=", 12.0, "primer ítem de 3 200 antes del minuto 12"),
        ("muertes", "<=", 6, "6 muertes o menos en toda la partida"),
        ("participacion", ">=", 0.40, "≥ 0,40 (kills+asistencias) por minuto"),
        ("oro20", ">=", 3000, "≥ 3 000 de oro sin gastar a los 20 min"),
        ("items20", ">=", 10, "≥ 10 compras a los 20 min"),
    ]
    salida = []
    for clave, signo, umbral, texto in candidatas:
        validas = [f for f in mias if isinstance(f.get(clave), (int, float))]
        if not validas:
            continue
        cumple = [f for f in validas
                  if (f[clave] <= umbral if signo == "<=" else f[clave] >= umbral)]
        gana = sum(1 for f in cumple if f["gane"])
        salida.append({"clave": clave, "umbral": umbral, "signo": signo, "texto": texto,
                       "n_cumple": len(cumple), "n": len(validas),
                       "victorias": gana,
                       "tasa_si": round(100 * gana / len(cumple), 1) if cumple else None,
                       "tasa_no": round(100 * (sum(1 for f in validas if f["gane"]) - gana)
                                        / max(1, len(validas) - len(cumple)), 1)})
    return salida


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Partidas del dueño vs benchmark de Abrams")
    p.add_argument("--matches", default="", help="ids separados por coma (defecto: /tmp/mis_con_demo.json)")
    p.add_argument("--json", default="", help="guarda el crudo en este JSON")
    p.add_argument("--sin-benchmark", action="store_true")
    p.add_argument("--bajar", action="store_true",
                   help="descarga el metadata que falte antes de medir")
    args = p.parse_args(argv)

    ids = ([int(x) for x in args.matches.replace(" ", "").split(",") if x]
           if args.matches else json.loads(IDS.read_text()))
    items = catalogo()

    if args.bajar:
        for m in ids:
            print(f"  metadata {m}: {bajar_metadata(m)}", file=sys.stderr)

    mias = [por_partida(m, items) for m in ids]
    with_demo = [f for f in mias if "demo" in f.get("fuente", [])]

    # el benchmark es del héroe que jugaste en cada partida: no se compara un Seven
    # contra la mediana de Abrams
    heroes = sorted({f.get("heroe") for f in with_demo if f.get("heroe")})
    benchs = {}
    if not args.sin_benchmark:
        benchs = {h: benchmark(h) for h in heroes}

    mismos = [f for f in with_demo if f.get("heroe") == HEROE_ABRAMS]
    otros = [f for f in with_demo if f.get("heroe") != HEROE_ABRAMS]
    tabla = resumen(mismos, (benchs.get(HEROE_ABRAMS) or {"filas": []})["filas"])
    pr = pruebas(mismos)
    rg = reglas(mismos)
    tabla_otros = {f["match"]: resumen([f], (benchs.get(f["heroe"]) or {"filas": []})["filas"])
                   for f in otros}

    crudo = {"generado": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
             "partidas_pedidas": len(ids), "partidas_con_demo": len(with_demo),
             "partidas": mias,
             "benchmark": {str(h): {"n": b["n"], "solo_12_jugadores": b["solo_12_jugadores"],
                                    "mediana": {k: v for k, v in
                                                resumen([], b["filas"])["benchmark"].items()}}
                           for h, b in benchs.items()},
             "resumen_abrams": tabla,
             "resumen_otro_heroe": tabla_otros,
             "pruebas_ganadas_perdidas": pr,
             "reglas_candidatas": rg}
    if args.json:
        Path(args.json).write_text(json.dumps(crudo, indent=1, ensure_ascii=False),
                                   encoding="utf-8")

    print(f"partidas: {len(ids)} pedidas, {len(with_demo)} con demo, "
          f"{len(mias) - len(with_demo)} solo metadata; "
          f"{len(mismos)} Abrams + {len(otros)} otro héroe")
    print("\n| partida | héroe | gane | min | 6400 | 3200 | items20 | oro10 | oro20 | m<10 | m | part | preámb | resid | recall |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for f in mias:
        def v(k, fmt="{}"):
            x = f.get(k)
            return "—" if x is None else fmt.format(x)
        cal = (f.get("calibracion") or {}).get("preambulo")
        print(f"| {f['match']} | {v('heroe')} | {'Sí' if f.get('gane') else 'No'} | "
              f"{v('duracion_s')} | {v('min6400', '{:.1f}')} | {v('min3200', '{:.1f}')} | "
              f"{v('items20')} | {v('oro10')} | {v('oro20')} | "
              f"{v('muertes10')} | {v('muertes')} | {v('participacion')} | "
              f"{cal if cal is not None else '—'} | {v('control_duracion_s')} | "
              f"{v('recall_meta', '{}%')} |")

    print("\n### medianas")
    print("| métrica | mías | mías·ganadas | mías·perdidas | benchmark | bench·ganadas | bench·perdidas |")
    print("|---|---|---|---|---|---|---|")
    for clave in CLAVES:
        if clave not in tabla["mias"] and clave not in tabla["benchmark"]:
            continue
        a = tabla["mias"].get(clave, {})
        b = tabla["benchmark"].get(clave, {})
        print(f"| {clave} | {a.get('todas')} | {a.get('ganadas')} | {a.get('perdidas')} | "
              f"{b.get('todas')} | {b.get('ganadas')} | {b.get('perdidas')} |")

    print("\n### ganadas vs perdidas (permutación, 20 000 remuestreos)")
    print("| métrica | media ganadas | media perdidas | delta | p |")
    print("|---|---|---|---|---|")
    for clave, v in pr.items():
        print(f"| {clave} | {v['media_ganadas']} | {v['media_perdidas']} | "
              f"{v['delta']} | {v['p']} |")
    print("\n### reglas candidatas")
    print("| regla | cumple | victorias | tasa si | tasa no |")
    print("|---|---|---|---|---|")
    for r in rg:
        print(f"| {r['texto']} | {r['n_cumple']}/{r['n']} | {r['victorias']} | "
              f"{r['tasa_si']} % | {r['tasa_no']} % |")
    return 0


if __name__ == "__main__":
    sys.exit(main())

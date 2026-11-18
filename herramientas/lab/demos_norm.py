#!/usr/bin/env python3
"""Normaliza las demos crudas del crawler a una fila por compra.

Qué produce
-----------
`datos/demos_norm.csv.gz` (o `.parquet` si hay pyarrow) con una fila por
`AbilitiesChangedEvent` de tipo compra (`change = 0`) y estas columnas:

    match_id, slot, hero_id, tick, segundos, item_id, item_nombre,
    coste_catalogo, oro_antes, pagado, descuento_componentes, franja,
    resultado, heroes_en_partida, n_asequibles, n_alternativas,
    comprado_es_max, rango_precio, pago_observado, pago_ambiguo,
    grafo_componentes, mediana_descuento, pausas_conocidas

Reglas (documentadas también en el informe)
-------------------------------------------
* `oro_antes`: saldo inmediatamente antes de la compra. Si en el tick de la
  compra hay un `delta` negativo, es `new_value - delta` (el saldo previo al
  cargo); si no, el último `new_value` con tick < t. Sin eventos previos: 600
  (oro inicial medido en todas las demos). La fórmula literal «último
  `new_value` <= tick» devolvería el saldo *después* del cargo y está mal.
* `pagado`: suma de los `delta` negativos del mismo `userid` en `tick ± 2`.
  Si no hay ninguno, `None` y `pago_observado = 0`. Si hay más de un delta
  negativo o más de una compra en la ventana, `pago_ambiguo = 1`.
* `descuento_componentes`: `coste_catalogo - pagado` cuando hay pago
  observado; `None` si no.
* Inventario: se reconstruye por slot con `change = 0` (alta) y `change = 2`
  (baja: venta o consumo en una mejora). `change = 5` no toca oro ni
  inventario en las 76 demos medidas (114 de 115 sin delta de oro), así que se
  ignora. El inventario que se usa para una compra es el estado **antes** de
  los eventos de ese tick, para que un componente consumido en la misma
  compra siga contando.
* Conjunto asequible: ítems comprables no poseídos. Con grafo de componentes:

      precio_neto = coste - suma(coste de los componentes que YA tiene)
      asequible   <=> precio_neto <= oro_antes
                   <=> coste <= oro_antes + valor_componentes_aplicables

  (el término `+ valor_componentes_aplicables` ya está dentro del precio neto:
  sumarlo otra vez al oro duplicaría el descuento). Sin grafo (186 de 250
  upgrades): `precio_neto = coste - mediana_descuento` del ítem (mediana
  observada, excluyendo la propia compra) y se compara con `oro_antes`.

Sin red, el script usa los cachés `datos/demos_meta.json` y
`datos/demos_aux.json`. Con `--descargar` los llena (metadata de la partida y
una consulta de demo por partida para pausas y mapa de slots).

Uso:
    python3 herramientas/lab/demos_norm.py --descargar
    python3 herramientas/lab/demos_norm.py
    python3 herramientas/lab/demos_norm.py --max-demos 10 --salida /tmp/x.csv.gz
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import json
import os
import shutil
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BASE_API = "https://api.deadlock-api.com"
AGENTE = "abrams-coach/lab-demos-norm/1"

TPS = 64.0
FRANJAS_S = (900.0, 1800.0)       # 0-15 min, 15-30 min, 30+ min (igual que corpus.py)
STEAM_BASE = 76561197960265728
ORO_INICIAL = 600
MIN_OBS_MEDIANA = 1               # con 1 observación ya hay mediana; se reporta n
MAX_SEGUNDOS_CONSULTA = 180

SQL_AUX = """SELECT 'mapa' AS tag, CAST(entity_index AS VARCHAR) AS a, CAST(MIN("m_steamID") AS VARCHAR) AS b, CAST(MIN("m_unLobbyPlayerSlot") AS VARCHAR) AS c, CAST(MIN("m_iTeamNum") AS VARCHAR) AS d
FROM CCitadelPlayerController GROUP BY entity_index
UNION ALL
SELECT 'pausa', CAST(MIN(tick) AS VARCHAR), CAST(CAST("m_pGameRules__m_nTotalPausedTicks" AS BIGINT) AS VARCHAR), '', '' FROM CCitadelGameRulesProxy
GROUP BY "m_pGameRules__m_nTotalPausedTicks"
ORDER BY 1, 2"""

COLUMNAS = [
    "match_id", "slot", "hero_id", "tick", "segundos", "segundos_fuente",
    "item_id", "item_nombre",
    "coste_catalogo", "oro_antes", "pagado", "descuento_componentes", "franja",
    "resultado", "heroes_en_partida", "slot_confianza", "n_asequibles", "n_alternativas",
    "n_alt_mismo_slot", "n_alt_50pct",
    "comprado_es_max", "rango_precio", "pago_observado", "pago_ambiguo",
    "grafo_componentes", "mediana_descuento", "pausas_conocidas",
]


# ------------------------------------------------------------------ utilidades

def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def leer_json(ruta, defecto=None):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def guardar_json(ruta, datos) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, ruta)


def leer_ndjson(ruta):
    filas = []
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                filas.append(json.loads(linea))
    return filas


def demos_completas(base: Path):
    """Directorios con las tres piezas del crawler. Ignora los que están a medias."""
    salida = []
    if not base.exists():
        return salida
    for d in sorted(base.iterdir(), key=lambda x: x.name):
        if not d.is_dir():
            continue
        if all((d / n).exists() for n in ("abilities.ndjson", "currency_gold.ndjson", "meta.json")):
            salida.append(d)
    return salida


def decodificar_u64(valor):
    """Los campos u64 llegan como hex little-endian («0300000000000000»)."""
    if valor is None:
        return None
    s = str(valor).strip()
    if not s:
        return None
    if len(s) >= 16 and all(c in "0123456789abcdefABCDEF" for c in s):
        return int.from_bytes(bytes.fromhex(s.zfill(16)), "little")
    return int(s)


def franja_de(segundos: float) -> int:
    return 0 if segundos < FRANJAS_S[0] else (1 if segundos < FRANJAS_S[1] else 2)


# ----------------------------------------------------------------------- pausas

def ticks_pausados(pausas, tick: int) -> int:
    """Ticks acumulados de pausa en ese tick, según tramos [(tick_inicio, acumulado)]."""
    actual = 0
    for inicio, acumulado in pausas or []:
        if tick < inicio:
            break
        actual = int(acumulado)
    return actual


def segundos_de_juego(tick: int, pausas=None) -> float:
    """Tick del demo -> segundo de partida, descontando pausas (sin preámbulo)."""
    return max(0.0, (int(tick) - ticks_pausados(pausas, tick)) / TPS)


# -------------------------------------------------------------------------- oro

def _indices_ventana(ticks, lo: int, hi: int):
    return bisect.bisect_left(ticks, lo), bisect.bisect_right(ticks, hi)


def oro_antes(eventos, ticks, tick: int) -> int:
    """Saldo inmediatamente antes de la compra del tick `tick`."""
    i = bisect.bisect_left(ticks, tick)
    j = bisect.bisect_right(ticks, tick)
    if i < j:
        mismo = eventos[i:j]
        negativos = [g for g in mismo if g["delta"] < 0]
        if negativos:
            g = negativos[-1]
            return int(g["new_value"] - g["delta"])
        return int(mismo[-1]["new_value"])
    if i > 0:
        return int(eventos[i - 1]["new_value"])
    return ORO_INICIAL


def pago_observado(eventos, ticks, tick: int):
    """(suma de deltas negativos en tick±2, n_deltas). (None, 0) si no hay."""
    lo, hi = _indices_ventana(ticks, tick - 2, tick + 2)
    deltas = [eventos[k]["delta"] for k in range(lo, hi) if eventos[k]["delta"] < 0]
    if not deltas:
        return None, 0
    return int(-sum(deltas)), len(deltas)


# ------------------------------------------------------------------ inventario

def _baja(inventario: Counter, iid: str) -> bool:
    if inventario.get(iid, 0) <= 0:
        return False
    inventario[iid] -= 1
    if inventario[iid] <= 0:
        del inventario[iid]
    return True


def compras_por_slot(eventos):
    """{slot: [eventos change=0 en orden de tick]}."""
    salida = defaultdict(list)
    for e in eventos:
        if int(e["change"]) == 0:
            salida[int(e["purchaser_player_slot"])].append(e)
    for lst in salida.values():
        lst.sort(key=lambda e: int(e["tick"]))
    return salida


def emparejar_slots(eventos, meta_partida):
    """Empareja el slot del evento (entidad-1) con el jugador de metadata.

    La demo no trae el mapa `CCitadelPlayerController` (la consulta de demo da
    429), así que se usa la huella de compras: el conjunto de ítems comprados
    de cada slot contra los `items` de cada jugador en metadata. Se exige
    margen sobre el segundo mejor; si no, `confianza=0`.
    """
    jugadores = [p for p in ((meta_partida or {}).get("players") or [])
                 if p.get("items")]
    compras = compras_por_slot(eventos)
    pares = []
    for slot, evs in compras.items():
        d = Counter(str(e["ability_id"]) for e in evs)
        for p in jugadores:
            m = Counter(str(it.get("item_id")) for it in (p.get("items") or []))
            inter = sum((d & m).values())
            union = sum((d | m).values())
            pares.append((inter / union if union else 0.0, slot, p))
    pares.sort(key=lambda x: -x[0])
    asignado, usados = {}, set()
    for score, slot, p in pares:
        if slot in asignado or p.get("player_slot") in usados:
            continue
        asignado[slot] = (score, p)
        usados.add(p.get("player_slot"))
    salida = {}
    for slot, (score, p) in asignado.items():
        segundos = [s for s, sl, q in pares if sl == slot and q is not p]
        segundo = max(segundos) if segundos else 0.0
        confianza = int(score >= 0.30 and score >= 1.5 * (segundo or 0.0))
        salida[slot] = {"jugador": p, "score": round(score, 3),
                        "segundo": round(segundo, 3), "confianza": confianza,
                        "via": "huella"}
    return salida


def resolver_slots(eventos, meta_partida, aux):
    """Mapa slot->jugador: primero el mapa exacto de la demo, si está cacheado."""
    jugadores = (meta_partida or {}).get("players") or []
    por_cuenta = {p.get("account_id"): p for p in jugadores
                  if p.get("account_id") is not None}
    mapa = (aux or {}).get("mapa") or {}
    salida = {}
    for slot in range(12):
        info = mapa.get(str(slot)) or mapa.get(slot)
        if not info:
            continue
        p = por_cuenta.get(info.get("account_id"))
        if p is None and info.get("lobby") is not None:
            p = next((x for x in jugadores
                      if x.get("player_slot") == info["lobby"]), None)
        if p is not None:
            salida[slot] = {"jugador": p, "score": 1.0, "segundo": 0.0,
                            "confianza": 2, "via": "mapa"}
    resto = emparejar_slots(eventos, meta_partida)
    for slot, info in resto.items():
        if slot not in salida:
            salida[slot] = info
    return salida


def alinear_tiempos(compras, items):
    """Segundos de juego (metadata) para cada compra, alineando por item_id.

    Los `items` de metadata traen la compra y su `game_time_s` (reloj de juego,
    ya sin pausas). Se elige la ocurrencia más cercana a `tick/64` para no
    confundirla con un ítem inicial o con una recompra.
    """
    if not items:
        return [None] * len(compras)
    usados, salida = set(), []
    for e in compras:
        iid = str(e["ability_id"])
        t0 = int(e["tick"]) / TPS
        cands = []
        for i, it in enumerate(items):
            if i in usados or str(it.get("item_id")) != iid:
                continue
            t = it.get("game_time_s")
            if t is None:
                continue
            dif = float(t) - t0
            # el reloj de juego nunca va por delante del tick; y una pausa
            # medida en estas demos no pasa de ~72 s. 150 s deja margen.
            if -150.0 <= dif <= 2.0:
                cands.append((abs(dif), i, float(t)))
        if not cands:
            salida.append(None)
            continue
        _, i, t = min(cands)
        usados.add(i)
        salida.append(t)
    return salida


def normalizar_demo(mid: int, meta_partida, eventos, oro, catalogo, componentes, aux):
    """Filas normalizadas de una partida (sin el conjunto asequible todavía)."""
    mid = int(mid)
    pausas = (aux or {}).get("pausas") or []
    pausas_ok = bool((aux or {}).get("pausas") is not None)
    mapa_slots = resolver_slots(eventos, meta_partida, aux)
    compras_slot = compras_por_slot(eventos)
    tiempos_slot = {}
    for slot, lst in compras_slot.items():
        info = mapa_slots.get(slot) or {}
        jugador = info.get("jugador") or {}
        tiempos_slot[slot] = alinear_tiempos(lst, jugador.get("items") or [])
    indice_tiempo = defaultdict(int)
    desfases = []
    for slot, lst in compras_slot.items():
        if int((mapa_slots.get(slot) or {}).get("confianza") or 0) < 1:
            continue
        for ev, t in zip(lst, tiempos_slot.get(slot) or []):
            if t is not None:
                desfases.append((int(ev["tick"]), int(ev["tick"]) / TPS - float(t)))
    desfases.sort()
    ticks_desfase = [x[0] for x in desfases]

    # oro por usuario, ordenado por tick
    por_usuario = defaultdict(list)
    for g in oro:
        por_usuario[int(g["userid"])].append(g)
    ticks_oro = {}
    for slot, lst in por_usuario.items():
        lst.sort(key=lambda g: int(g["tick"]))
        ticks_oro[slot] = [int(g["tick"]) for g in lst]

    # metadata de la partida: cuenta -> héroe; equipo por slot vía mapa
    jugadores = (meta_partida or {}).get("players") or []
    heroes_partida = sorted({int(p["hero_id"]) for p in jugadores
                             if p.get("hero_id") is not None})
    heroes_txt = "|".join(str(h) for h in heroes_partida)
    ganador = (meta_partida or {}).get("winning_team")

    filas = []
    inventario = defaultdict(Counter)   # slot -> Counter(item_id)
    stats = Counter()
    por_tick = defaultdict(list)
    for e in eventos:
        por_tick[int(e["tick"])].append(e)
    ticks_compra = defaultdict(list)
    for e in eventos:
        if int(e["change"]) == 0:
            ticks_compra[int(e["purchaser_player_slot"])].append(int(e["tick"]))
    for lst in ticks_compra.values():
        lst.sort()

    for tick in sorted(por_tick):
        mismo = por_tick[tick]
        compras = [e for e in mismo if int(e["change"]) == 0]
        # instantánea ANTES de los eventos del tick: un componente consumido
        # por la compra de este tick sigue contando como disponible.
        instantaneas = {
            int(e["purchaser_player_slot"]): sorted(inventario.get(
                int(e["purchaser_player_slot"]), Counter()))
            for e in mismo
        }

        for e in compras:
            slot = int(e["purchaser_player_slot"])
            iid = str(e["ability_id"])
            item = catalogo.get(iid)
            if not item:
                stats["sin_catalogo"] += 1
                continue
            costo = int(item.get("costo") or 0)
            eventos_oro = por_usuario.get(slot, [])
            ticks = ticks_oro.get(slot, [])
            pagado, n_neg = pago_observado(eventos_oro, ticks, tick)
            desc = None if pagado is None else costo - pagado
            oro_t = oro_antes(eventos_oro, ticks, tick)
            _tc = ticks_compra.get(slot, [])
            n_compras = (bisect.bisect_right(_tc, tick + 2)
                         - bisect.bisect_left(_tc, tick - 2))

            info_slot = mapa_slots.get(slot) or {}
            jugador = info_slot.get("jugador") or {}
            heroe = jugador.get("hero_id")
            equipo = jugador.get("team")
            resultado = None
            if equipo is not None and ganador is not None:
                resultado = "victoria" if int(equipo) == int(ganador) else "derrota"

            idx_t = indice_tiempo[slot]
            indice_tiempo[slot] += 1
            t_meta = (tiempos_slot.get(slot) or [])[idx_t] \
                if idx_t < len(tiempos_slot.get(slot) or []) else None
            if info_slot.get("via") == "mapa" and pausas_ok:
                seg = segundos_de_juego(tick, pausas)
                fuente = "demo"
            elif t_meta is not None:
                seg = float(t_meta)
                fuente = "metadata"
            elif pausas_ok:
                seg = segundos_de_juego(tick, pausas)
                fuente = "demo"
            elif desfases:
                # compra sin huella en metadata: se aplica el desfase de pausa
                # observado en la compra alineada más cercana hacia atrás.
                i = bisect.bisect_right(ticks_desfase, tick) - 1
                off = desfases[max(0, i)][1]
                seg = int(tick) / TPS - off
                fuente = "vecino"
            else:
                seg = int(tick) / TPS
                fuente = "tick"
            filas.append({
                "match_id": mid,
                "slot": slot,
                "hero_id": heroe,
                "tick": tick,
                "segundos": round(seg, 3),
                "segundos_fuente": fuente,
                "item_id": iid,
                "item_nombre": item.get("nombre") or "",
                "coste_catalogo": costo,
                "oro_antes": oro_t,
                "pagado": pagado,
                "descuento_componentes": desc,
                "franja": franja_de(seg),
                "resultado": resultado,
                "heroes_en_partida": heroes_txt,
                "slot_confianza": int(info_slot.get("confianza") or 0),
                "_inventario": instantaneas.get(slot, []),
                "_pago_ambiguo": int(n_neg > 1 or n_compras > 1),
                "_pausas_ok": int(fuente in ("metadata", "demo")),
                "_conf_slot": int(info_slot.get("confianza") or 0),
                "_grafo": None,
                "_mediana": None,
                "_desc_observado": desc,
            })

        for e in mismo:
            cambio = int(e["change"])
            slot_e = int(e["purchaser_player_slot"])
            if cambio == 0:
                inventario[slot_e][str(e["ability_id"])] += 1
            elif cambio == 2:
                stats["bajas"] += 1
                if _baja(inventario[slot_e], str(e["ability_id"])):
                    stats["bajas_con_stock"] += 1
                else:
                    stats["bajas_sin_stock"] += 1
            elif cambio == 5:
                stats["change5"] += 1
            else:
                stats["change_otro"] += 1

    return filas, stats


# ------------------------------------------------------------- conjunto asequible

def medianas_por_item(filas):
    """Mediana del descuento observado por ítem, y la lista para el leave-one-out.

    Solo usa pagos no ambiguos y descuentos dentro de [0, coste].
    """
    valores = defaultdict(list)
    for f in filas:
        d = f.get("_desc_observado")
        if d is None or f.get("_pago_ambiguo"):
            continue
        if 0 <= d <= (f["coste_catalogo"] or 0):
            valores[f["item_id"]].append(d)
    return valores


def mediana_loo(lista, quitar=None):
    """Mediana de la lista; si `quitar` está, se descuenta una ocurrencia."""
    if not lista:
        return 0.0
    datos = list(lista)
    if quitar is not None and datos:
        try:
            datos.remove(quitar)
        except ValueError:
            pass
    if not datos:
        return 0.0
    return float(statistics.median(datos))


def conjunto_asequible(oro: int, poseidos, catalogo, componentes, mediana,
                       comprables):
    """Lista [(item_id, precio_neto)] asequible con ese oro e inventario."""
    props = set(poseidos or ())
    disponibles = []
    for iid in comprables:
        item = catalogo[iid]
        costo = int(item.get("costo") or 0)
        if costo <= 0 or iid in props:
            continue
        if iid in componentes:
            # precio neto = catálogo - lo que el jugador ya tiene de sus componentes.
            # Es equivalente a "coste <= oro + valor_componentes_aplicables" sin
            # sumar dos veces el descuento.
            comps = componentes[iid]
            valor_propio = sum(int(catalogo[c].get("costo") or 0) for c in comps
                               if c in catalogo and c in props)
            neto = max(0, costo - valor_propio)
        else:
            # sin grafo: el descuento típico observado para ese ítem.
            neto = max(0, costo - int(round(mediana or 0)))
        if neto <= int(oro):
            disponibles.append((iid, neto))
    return disponibles


def aplicar_conjunto(filas, catalogo, componentes, valores, comprables):
    """Rellena n_asequibles, n_alternativas, rango_precio y comprado_es_max."""
    for f in filas:
        iid = f["item_id"]
        lista = valores.get(iid, [])
        med = mediana_loo(lista, f.get("_desc_observado"))
        if iid in componentes:
            med = None
        disponibles = conjunto_asequible(f["oro_antes"], f["_inventario"], catalogo,
                                         componentes, med, comprables)
        ids = {x[0] for x in disponibles}
        comprado_en = iid in ids
        f["_grafo"] = int(iid in componentes)
        f["_mediana"] = med
        f["n_asequibles"] = len(disponibles)
        f["n_alternativas"] = len(disponibles) - (1 if comprado_en else 0)
        slot_b = catalogo[iid].get("slot")
        f["n_alt_mismo_slot"] = sum(1 for x in disponibles
                                    if x[0] != iid
                                    and catalogo[x[0]].get("slot") == slot_b)
        f["n_alt_50pct"] = sum(1 for x in disponibles
                               if x[0] != iid
                               and int(catalogo[x[0]].get("costo") or 0) >= 0.5 * f["coste_catalogo"])
        if comprado_en:
            coste = f["coste_catalogo"]
            f["rango_precio"] = 1 + sum(1 for x in disponibles
                                        if int(catalogo[x[0]].get("costo") or 0) > coste)
        else:
            f["rango_precio"] = 0
        f["comprado_es_max"] = int(comprado_en and f["rango_precio"] == 1)
    return filas


# ----------------------------------------------------------------------- salida

def escribir_tabla(filas, ruta: Path):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.suffix == ".parquet":
        import pyarrow as pa
        import pyarrow.parquet as pq
        tabla = pa.Table.from_pylist([{k: f.get(k) for k in COLUMNAS} for f in filas])
        pq.write_table(tabla, ruta, compression="zstd")
        return "parquet"
    with gzip.open(ruta, "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, extrasaction="ignore")
        w.writeheader()
        for f in filas:
            w.writerow({k: f.get(k) for k in COLUMNAS})
    return "csv.gz"


def resumen(filas, stats, n_demos, n_demos_con_aux, n_demos_con_meta,
            n_componentes=0):
    n = len(filas)
    if not n:
        return {"n_filas": 0}
    con_pago = [f for f in filas if f["pago_observado"]]
    pagos = [f for f in con_pago if not f["pago_ambiguo"]]
    iguales = sum(1 for f in pagos if f["pagado"] == f["coste_catalogo"])
    menos = sum(1 for f in pagos if f["pagado"] > 0 and f["pagado"] < f["coste_catalogo"])
    mas = sum(1 for f in pagos if f["pagado"] > f["coste_catalogo"])
    desc = sorted(f["descuento_componentes"] for f in pagos
                  if f["descuento_componentes"] is not None)
    tam = sorted(f["n_asequibles"] for f in filas)
    alt = sorted(f["n_alternativas"] for f in filas)
    con_bought = [f for f in filas if f["rango_precio"] > 0]
    maxi = [f for f in filas if f["comprado_es_max"]]

    def pct(k, total):
        return round(100.0 * k / total, 2) if total else None

    def p(xs, q):
        if not xs:
            return None
        return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]

    por_franja = {}
    for fr in (0, 1, 2):
        sub = [f for f in filas if f["franja"] == fr]
        por_franja[str(fr)] = {
            "n": len(sub),
            "pct_2_alternativas": pct(sum(1 for f in sub if f["n_alternativas"] >= 2), len(sub)),
            "mediana_asequibles": p( sorted(f["n_asequibles"] for f in sub), 0.5) if sub else None,
        }

    return {
        "n_filas": n,
        "n_demos": n_demos,
        "demos_con_aux": n_demos_con_aux,
        "demos_con_meta": n_demos_con_meta,
        "n_jugador_partida": len({(f["match_id"], f["slot"]) for f in filas}),
        "n_items_distintos": len({f["item_id"] for f in filas}),
        "pago": {
            "observado": len(con_pago),
            "pct_observado": pct(len(con_pago), n),
            "ambiguo": sum(1 for f in filas if f["pago_ambiguo"]),
            "sin_pago": n - len(con_pago),
            "pct_catalogo": pct(iguales, len(pagos)),
            "pct_menos": pct(menos, len(pagos)),
            "pct_mas": pct(mas, len(pagos)),
            "descuento_p10": p(desc, 0.10),
            "descuento_mediana": p(desc, 0.50),
            "descuento_p90": p(desc, 0.90),
        },
        "cobertura": {
            "pct_1_alternativa": pct(sum(1 for f in filas if f["n_alternativas"] >= 1), n),
            "pct_2_alternativas": pct(sum(1 for f in filas if f["n_alternativas"] >= 2), n),
            "pct_3_alternativas": pct(sum(1 for f in filas if f["n_alternativas"] >= 3), n),
            "pct_5_alternativas": pct(sum(1 for f in filas if f["n_alternativas"] >= 5), n),
            "pct_2_alternativas_mismo_slot": pct(sum(1 for f in filas if f["n_alt_mismo_slot"] >= 2), n),
            "mediana_alternativas_mismo_slot": p(sorted(f["n_alt_mismo_slot"] for f in filas), 0.5),
            "pct_2_alternativas_50pct": pct(sum(1 for f in filas if f["n_alt_50pct"] >= 2), n),
            "mediana_alt_50pct": p(sorted(f["n_alt_50pct"] for f in filas), 0.5),
            "pct_conjunto_vacio": pct(sum(1 for f in filas if f["n_asequibles"] == 0), n),
            "tamano_p10": p(tam, 0.10),
            "tamano_mediana": p(tam, 0.50),
            "tamano_p90": p(tam, 0.90),
            "tamano_max": max(tam) if tam else None,
            "alternativas_p10": p(alt, 0.10),
            "alternativas_mediana": p(alt, 0.50),
            "alternativas_p90": p(alt, 0.90),
            "pct_comprado_en_conjunto": pct(len(con_bought), n),
            "pct_comprado_mas_caro": pct(len(maxi), n),
            "pct_comprado_mas_caro_si_en_conjunto": pct(len(maxi), len(con_bought)),
        },
        "por_franja": por_franja,
        "componentes": {
            "items_con_grafo": n_componentes,
            "pct_filas_item_con_grafo": pct(sum(1 for f in filas if f["_grafo"]), n),
            "bajas_change2": stats.get("bajas", 0),
            "bajas_con_stock": stats.get("bajas_con_stock", 0),
            "bajas_sin_stock": stats.get("bajas_sin_stock", 0),
            "change5_ignorados": stats.get("change5", 0),
            "sin_catalogo": stats.get("sin_catalogo", 0),
        },
        "reconstruccion": {
            "pct_con_heroe": pct(sum(1 for f in filas if f["hero_id"] is not None), n),
            "pct_con_resultado": pct(sum(1 for f in filas if f["resultado"]), n),
            "pct_con_pausas": pct(sum(1 for f in filas if f["pausas_conocidas"]), n),
            "pct_sin_pago": pct(n - len(con_pago), n),
            "pct_segundos_metadata": pct(sum(1 for f in filas if f.get("segundos_fuente") == "metadata"), n),
            "pct_segundos_demo": pct(sum(1 for f in filas if f.get("segundos_fuente") == "demo"), n),
            "pct_segundos_vecino": pct(sum(1 for f in filas if f.get("segundos_fuente") == "vecino"), n),
            "pct_segundos_tick": pct(sum(1 for f in filas if f.get("segundos_fuente") == "tick"), n),
            "pct_slot_emparejado": pct(sum(1 for f in filas if f.get("_conf_slot")), n),
            "pct_slot_confianza_alta": pct(sum(1 for f in filas if f.get("_conf_slot") == 1), n),
            "pct_slot_mapa": pct(sum(1 for f in filas if f.get("_conf_slot") == 2), n),
        },
    }


# ------------------------------------------------------------------ red: cachés

class Limitador:
    def __init__(self, rpm: float):
        self.intervalo = 60.0 / max(1.0, rpm)
        self._lock = threading.Lock()
        self._siguiente = 0.0

    def esperar(self):
        with self._lock:
            ahora = time.monotonic()
            cuando = max(ahora, self._siguiente)
            self._siguiente = cuando + self.intervalo
        falta = cuando - time.monotonic()
        if falta > 0:
            time.sleep(falta)


_LIMITADOR = Limitador(45.0)


def _http(url, datos=None, timeout=120):
    req = urllib.request.Request(url, data=datos,
                                 headers={"User-Agent": AGENTE,
                                          "Content-Type": "application/json"},
                                 method="POST" if datos is not None else "GET")
    return urllib.request.urlopen(req, timeout=timeout)


def _json_http(url, datos=None, timeout=120):
    for intento in range(6):
        _LIMITADOR.esperar()
        try:
            with _http(url, datos, timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                espera = 60.0
                try:
                    espera = max(60.0, float(e.headers.get("Retry-After") or 60))
                except (TypeError, ValueError):
                    pass
                log(f"429: espero {espera:.0f}s")
                time.sleep(espera)
                continue
            if e.code == 404:
                raise
            if intento == 5:
                raise
            time.sleep(3)
        except (urllib.error.URLError, TimeoutError, OSError):
            if intento == 5:
                raise
            time.sleep(3)
    raise RuntimeError(f"sin respuesta: {url}")


def descargar_metadata(mid: int):
    d = _json_http(f"{BASE_API}/v1/matches/{mid}/metadata?include_player_info=true")
    mi = d.get("match_info") or {}
    return {
        "winning_team": mi.get("winning_team"),
        "duration_s": mi.get("duration_s"),
        "players": [{
            "account_id": p.get("account_id"),
            "player_slot": p.get("player_slot"),
            "team": p.get("team"),
            "hero_id": p.get("hero_id"),
            "items": [{"item_id": str(it.get("item_id")),
                       "game_time_s": it.get("game_time_s"),
                       "sold_time_s": it.get("sold_time_s")}
                      for it in (p.get("items") or [])],
        } for p in (mi.get("players") or [])],
    }


def _descomprimir(crudo: bytes) -> bytes:
    try:
        import zstandard
        return zstandard.ZstdDecompressor().decompress(crudo)
    except ImportError:
        pass
    for cmd in (["zstd", "-dc"], ["unzstd", "-c"]):
        if shutil.which(cmd[0]):
            p = subprocess.run(cmd, input=crudo, capture_output=True)
            if p.returncode == 0:
                return p.stdout
    raise RuntimeError("no hay zstd para descomprimir")


def descargar_aux(mid: int):
    cola = _json_http(BASE_API + "/v1/matches/demo/query",
                      json.dumps({"match_id": mid, "query": SQL_AUX,
                                  "format": "ndjson"}).encode())
    jid = cola.get("job_id")
    if not jid:
        raise RuntimeError(f"sin job_id: {cola}")
    inicio = time.time()
    while time.time() - inicio < MAX_SEGUNDOS_CONSULTA:
        time.sleep(3.0)
        estado = _json_http(f"{BASE_API}/v1/matches/demo/query/{jid}")
        st = estado.get("status")
        if st == "done":
            with _http(estado["result_url"], timeout=180) as r:
                crudo = r.read()
            texto = _descomprimir(crudo).decode("utf-8")
            pausas, mapa = [], {}
            for linea in texto.splitlines():
                if not linea.strip():
                    continue
                x = json.loads(linea)
                if x.get("tag") == "pausa":
                    pausas.append([int(x["a"]), int(x["b"])])
                elif x.get("tag") == "mapa":
                    entidad = int(x["a"])
                    if not 1 <= entidad <= 12:
                        continue
                    steam = decodificar_u64(x.get("b"))
                    slot = entidad - 1
                    mapa[str(slot)] = {
                        "entity_index": entidad,
                        "steam_id": steam,
                        "account_id": (steam - STEAM_BASE) if steam else None,
                        "lobby": decodificar_u64(x.get("c")),
                        "team": int(x["d"]) if x.get("d") not in (None, "") else None,
                    }
            pausas.sort()
            return {"pausas": pausas, "mapa": mapa}
        if st in ("failed", "error", "cancelled", "expired"):
            raise RuntimeError(f"job {st}: {estado}")
    raise RuntimeError("timeout de la consulta de demo")


def completar_caches(demos, ruta_meta: Path, ruta_aux: Path, paralelo=3,
                     rpm=45.0, max_demos=0):
    global _LIMITADOR
    _LIMITADOR = Limitador(rpm)
    meta = leer_json(ruta_meta, {}) or {}
    aux = leer_json(ruta_aux, {}) or {}
    pendientes_meta = [d for d in demos if str(int(d.name)) not in meta]
    pendientes_aux = [d for d in demos if str(int(d.name)) not in aux]
    if max_demos:
        pendientes_meta = pendientes_meta[:max_demos]
        pendientes_aux = pendientes_aux[:max_demos]
    log(f"metadata pendientes: {len(pendientes_meta)} · aux pendientes: {len(pendientes_aux)}")

    def una_meta(d):
        mid = int(d.name)
        try:
            return mid, descargar_metadata(mid), None
        except Exception as e:  # noqa: BLE001
            return mid, None, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=paralelo) as ex:
        for fut in as_completed([ex.submit(una_meta, d) for d in pendientes_meta]):
            mid, datos, err = fut.result()
            if datos:
                meta[str(mid)] = datos
                guardar_json(ruta_meta, meta)
            else:
                log(f"{mid}: metadata falló — {err}")
    log(f"metadata en caché: {len(meta)}")

    def una_aux(d):
        mid = int(d.name)
        try:
            return mid, descargar_aux(mid), None
        except Exception as e:  # noqa: BLE001
            return mid, None, f"{type(e).__name__}: {e}"

    fallos = 0
    with ThreadPoolExecutor(max_workers=paralelo) as ex:
        for fut in as_completed([ex.submit(una_aux, d) for d in pendientes_aux]):
            mid, datos, err = fut.result()
            if datos:
                aux[str(mid)] = datos
                guardar_json(ruta_aux, aux)
            else:
                fallos += 1
                aux[str(mid)] = {"error": err, "pausas": None, "mapa": {}}
                guardar_json(ruta_aux, aux)
                log(f"{mid}: aux falló — {err}")
    log(f"aux en caché: {len(aux)} (fallos nuevos: {fallos})")


# ----------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--demos", default=str(RAIZ / "datos" / "demos"))
    ap.add_argument("--catalogo", default=str(RAIZ / "data" / "catalogo.json"))
    ap.add_argument("--componentes", default=str(RAIZ / "data" / "componentes.json"))
    ap.add_argument("--cache-meta", default=str(RAIZ / "datos" / "demos_meta.json"))
    ap.add_argument("--cache-aux", default=str(RAIZ / "datos" / "demos_aux.json"))
    ap.add_argument("--salida", default=str(RAIZ / "datos" / "demos_norm.csv.gz"))
    ap.add_argument("--resumen", default=str(RAIZ / "informes" / "lab"
                                             / "V3-NORMALIZACION-2026-11-18.json"))
    ap.add_argument("--descargar", action="store_true",
                    help="llena metadata y pausas/mapa desde la API")
    ap.add_argument("--paralelo", type=int, default=3)
    ap.add_argument("--rpm", type=float, default=45.0)
    ap.add_argument("--max-demos", type=int, default=0)
    args = ap.parse_args(argv)

    catalogo = leer_json(args.catalogo, {}) or {}
    componentes = leer_json(args.componentes, {}) or {}
    if not catalogo:
        sys.exit(f"no hay catálogo en {args.catalogo}")
    comprables = [iid for iid, d in catalogo.items()
                  if d.get("comprable") and int(d.get("costo") or 0) > 0]
    log(f"catálogo: {len(catalogo)} upgrades · comprables: {len(comprables)} · "
        f"con grafo: {len(componentes)}")

    demos = demos_completas(Path(args.demos))
    if args.max_demos:
        demos = demos[:args.max_demos]
    log(f"demos completas: {len(demos)}")
    if not demos:
        sys.exit(f"no hay demos completas en {args.demos}")

    if args.descargar:
        completar_caches(demos, Path(args.cache_meta), Path(args.cache_aux),
                         paralelo=args.paralelo, rpm=args.rpm,
                         max_demos=args.max_demos)

    meta_cache = leer_json(args.cache_meta, {}) or {}
    aux_cache = leer_json(args.cache_aux, {}) or {}

    filas, stats = [], Counter()
    con_aux = con_meta = 0
    for d in demos:
        mid = int(d.name)
        try:
            eventos = leer_ndjson(d / "abilities.ndjson")
            oro = leer_ndjson(d / "currency_gold.ndjson")
        except (OSError, ValueError) as e:
            log(f"{mid}: no se pudo leer — {e}")
            continue
        aux = aux_cache.get(str(mid))
        meta_partida = meta_cache.get(str(mid))
        if aux is not None:
            con_aux += 1
        if meta_partida is not None:
            con_meta += 1
        f, st = normalizar_demo(mid, meta_partida, eventos, oro, catalogo,
                                componentes, aux)
        filas.extend(f)
        stats.update(st)
    log(f"filas base: {len(filas)}")

    # mediana empírica por ítem (leave-one-out en la propia compra)
    valores = medianas_por_item(filas)
    con_desc = sum(1 for f in filas if (f.get("_desc_observado") or 0) > 0)
    log(f"ítems con descuento observado: {len(valores)} · filas con descuento > 0: {con_desc}")

    aplicar_conjunto(filas, catalogo, componentes, valores, comprables)

    for f in filas:
        f["pago_observado"] = int(f["pagado"] is not None)
        f["pago_ambiguo"] = int(f["_pago_ambiguo"])
        f["pausas_conocidas"] = int(f["_pausas_ok"])
        f["grafo_componentes"] = int(f["_grafo"] or 0)
        f["mediana_descuento"] = ("" if f["_mediana"] is None
                                  else round(float(f["_mediana"]), 2))

    formato = escribir_tabla(filas, Path(args.salida))
    res = resumen(filas, stats, len(demos), con_aux, con_meta,
                  len(componentes))
    res["formato"] = formato
    res["salida"] = str(args.salida)
    res["ruta_catalogo"] = str(args.catalogo)
    res["ruta_componentes"] = str(args.componentes)
    res["filas_con_aux"] = con_aux
    guardar_json(args.resumen, res)

    log(f"tabla: {args.salida} ({formato}, {os.path.getsize(args.salida)/1e6:.2f} MB)")
    log(f"resumen: {args.resumen}")
    log(f"cobertura ≥2 alternativas: {res['cobertura']['pct_2_alternativas']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

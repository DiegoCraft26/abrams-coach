#!/usr/bin/env python3
"""Baja partidas de Abrams de una cuenta y arma `data/replay_cache.json`.

Uso:
    python3 herramientas/datos/descargar_partidas.py --cuenta TU_STEAMID64
    python3 herramientas/datos/descargar_partidas.py --cuenta TU_STEAMID64 --cuantas 120

La cuenta no viaja en el repo: es tuya y se pasa por parámetro. El historial se pide
al API público de Deadlock (`/v1/players/{cuenta}/match-history`), se filtra a Abrams
(hero_id 6) y de cada partida se guarda el detalle que el motor usa para medir.
"""
import argparse
import json
import os
import sys
import time
import urllib.request

# Este script vive en herramientas/datos/: la raíz del repo está 3
# niveles arriba, no en el directorio del archivo.
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SALIDA = os.path.join(RAIZ, "data", "replay_cache.json")
H = {"User-Agent": "abrams-coach/1.0", "Accept": "application/json"}
HEROE_ABRAMS = 6


def get(u, intentos=3):
    for i in range(intentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=H),
                                        timeout=120) as r:
                return json.load(r)
        except Exception:                                          # noqa: BLE001
            if i == intentos - 1:
                return None
            time.sleep(2 * (i + 1))


def historial(cuenta, limite):
    """match_id de las partidas de Abrams de esa cuenta, de la más nueva a la más vieja."""
    d = get(f"https://api.deadlock-api.com/v1/players/{cuenta}/match-history"
            f"?limit={limite}")
    if not isinstance(d, list):
        return []
    return [m for m in d if m.get("hero_id") == HEROE_ABRAMS]


def main(cuenta, cuantas=60):
    cache = json.load(open(SALIDA)) if os.path.exists(SALIDA) else []
    vistos = {c["match_id"] for c in cache}
    partidas = historial(cuenta, max(cuantas * 4, 100))
    if not partidas:
        print("el API no devolvió partidas de Abrams para esa cuenta (¿existe?)")
        return 1
    nuevas = 0
    for m in partidas:
        if nuevas >= cuantas:
            break
        mid = m["match_id"]
        if mid in vistos:
            continue
        d = get(f"https://api.deadlock-api.com/v1/matches/{mid}/metadata"
                f"?include_player_info=true")
        if not d:
            continue
        mi = d.get("match_info") or {}
        ab = [p for p in mi.get("players", [])
              if p.get("hero_id") == HEROE_ABRAMS and p.get("account_id") == cuenta]
        if not ab or not ab[0].get("items") or not ab[0].get("stats"):
            continue
        p = ab[0]
        cache.append({
            "match_id": mid, "duracion_s": mi.get("duration_s"), "mia": True,
            "yo": {"slot": p["player_slot"], "team": p["team"],
                   "items": [{"t": it["game_time_s"], "id": str(it["item_id"]),
                              "vendido": it.get("sold_time_s") or 0}
                             for it in p["items"]],
                   "stats": [{"t": s["time_stamp_s"], "neto": s["net_worth"]}
                             for s in p["stats"]]},
            "jugadores": [{"slot": x["player_slot"], "team": x["team"],
                           "hero": x["hero_id"]}
                          for x in mi.get("players", [])],
            "gane": mi.get("winning_team") == p["team"],
        })
        vistos.add(mid)
        nuevas += 1
        if nuevas % 10 == 0:
            json.dump(cache, open(SALIDA, "w"))
            print(f"  {nuevas} nuevas ({len(cache)} total)", flush=True)
        time.sleep(0.2)
    json.dump(cache, open(SALIDA, "w"))
    print(f"listo: {nuevas} nuevas, {len(cache)} en caché")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cuenta", type=int, required=True,
                    help="tu SteamID64 (el perfil dueño de las partidas)")
    ap.add_argument("--cuantas", type=int, default=60,
                    help="partidas nuevas como máximo (default 60)")
    a = ap.parse_args()
    sys.exit(main(a.cuenta, a.cuantas))

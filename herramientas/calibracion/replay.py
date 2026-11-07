#!/usr/bin/env python3
"""Validación con partidas reales: rejuega compras de Abrams y mide si el motor acierta.

No necesita el juego ni la pantalla: toma el historial real de compras de cada partida,
reconstruye el estado en cada momento y compara la recomendación con lo que el jugador
compró de verdad.
"""
import argparse, json, os, random, sys, urllib.parse, urllib.request
sys.path.insert(0, RAIZ)
from coach.motor_api import Motor

# Este script vive en herramientas/calibracion/: la raíz del repo está 2
# niveles arriba, no en el directorio del archivo.
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

API = "https://api.deadlock-api.com"
H = {"User-Agent": "abrams-coach/1.0", "Accept": "application/json"}
DIR = RAIZ


def get(path, **q):
    u = API + path + ("?" + urllib.parse.urlencode(q) if q else "")
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=120) as r:
                return json.load(r)
        except Exception:
            if i == 2:
                return None
    return None


def partidas_con_abrams(cuantas, ruta_cache=os.path.join(DIR, "data", "replay_cache.json")):
    if os.path.exists(ruta_cache):
        cache = json.load(open(ruta_cache))
        if len(cache) >= cuantas:
            return cache[:cuantas]
    else:
        cache = []
    recientes = get("/v1/matches/recently-fetched") or []
    for m in recientes:
        if len(cache) >= cuantas:
            break
        mid = m["match_id"]
        if any(x.get("match_id") == mid for x in cache):
            continue
        d = get(f"/v1/matches/{mid}/metadata", include_player_info="true")
        if not d:
            continue
        mi = d.get("match_info") or {}
        ab = [p for p in mi.get("players", []) if p.get("hero_id") == 6]
        if not ab:
            continue
        p = ab[0]
        if not p.get("items") or not p.get("stats"):
            continue
        cache.append({
            "match_id": mid,
            "duracion_s": mi.get("duration_s"),
            "yo": {
                "slot": p["player_slot"], "team": p["team"],
                "items": [{"t": it["game_time_s"], "id": str(it["item_id"]),
                           "vendido": it.get("sold_time_s") or 0} for it in p["items"]],
                "stats": [{"t": s["time_stamp_s"], "neto": s["net_worth"]} for s in p["stats"]],
            },
            "jugadores": [{"slot": x["player_slot"], "team": x["team"], "hero": x["hero_id"]}
                          for x in mi.get("players", [])],
            "gane": mi.get("winning_team") == p["team"],
        })
        json.dump(cache, open(ruta_cache, "w"))
    return cache[:cuantas]


def almas_en(stats, t):
    """Interpola el net worth en el segundo t."""
    if not stats:
        return None
    if t <= stats[0]["t"]:
        return stats[0]["neto"]
    for a, b in zip(stats, stats[1:]):
        if a["t"] <= t <= b["t"]:
            if b["t"] == a["t"]:
                return b["neto"]
            f = (t - a["t"]) / (b["t"] - a["t"])
            return int(a["neto"] + f * (b["neto"] - a["neto"]))
    return stats[-1]["neto"]


def estado_en(partida, t, heroes_por_id):
    yo = partida["yo"]
    propios = [i["id"] for i in yo["items"]
               if i["t"] <= t and (not i["vendido"] or i["vendido"] > t)]
    enemigos, aliados = [], []
    for j in partida["jugadores"]:
        if j["slot"] == yo["slot"]:
            continue
        nombre = heroes_por_id.get(str(j["hero"]), str(j["hero"]))
        (enemigos if j["team"] != yo["team"] else aliados).append({"heroe": nombre})
    return {"t": t, "yo": {"heroe": "Abrams", "almas": almas_en(yo["stats"], t), "items": propios},
            "enemigos": enemigos, "aliados": aliados, "confianza": 1.0, "fuente": "replay"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--partidas", type=int, default=15)
    ap.add_argument("--desde-min", type=int, default=10, help="ignora la apertura")
    ap.add_argument("--desde-partida", type=int, default=0)
    a = ap.parse_args()

    m = Motor()
    heroes = {k: v["nombre"].lower().replace(" ", "_") for k, v in json.load(
        open(os.path.join(DIR, "data", "heroes.json"))).items()}
    partidas = partidas_con_abrams(a.partidas)
    print(f"partidas con Abrams: {len(partidas)}")

    aciertos1 = aciertos3 = total = 0
    por_partida = []
    ejemplos = []
    for partida in partidas[a.desde_partida:]:
        p1 = p3 = n = 0
        compras = [i for i in partida["yo"]["items"]
                   if i["t"] >= a.desde_min*60 and i["id"] in m.conoc["items"]]
        for i, compra in enumerate(compras):
            t = compra["t"]
            estado = estado_en(partida, t, heroes)
            if not estado["yo"]["almas"] or not estado["enemigos"]:
                continue
            r = m.analizar_dict(estado)
            recos = [x["id"] for x in r["recomendaciones"]]
            n += 1
            if recos and recos[0] == compra["id"]:
                p1 += 1
            if compra["id"] in recos:
                p3 += 1
            elif len(ejemplos) < 6 and n < 60:
                ejemplos.append({
                    "match": partida["match_id"], "min": t//60,
                    "recomendo": [x["nombre"] for x in r["recomendaciones"]][:2],
                    "compro": m.conoc["items"].get(compra["id"], {}).get("nombre", compra["id"]),
                })
        if n:
            por_partida.append((p1/n, p3/n, n))
            aciertos1 += p1; aciertos3 += p3; total += n

    if not total:
        print("sin muestras: revisa los filtros")
        return 1
    print(f"\ncompras evaluadas: {total}")
    print(f"acierto top-1: {aciertos1/total*100:.1f}%")
    print(f"acierto top-3: {aciertos3/total*100:.1f}%")
    print(f"partidas: {len(por_partida)}  · mediana top-1 por partida: "
          f"{sorted(x[0] for x in por_partida)[len(por_partida)//2]*100:.1f}%")
    print("\nejemplos de desacuerdo:")
    for e in ejemplos:
        print(f"  min {e['min']:>2} · recomendó {e['recomendo']} · compró {e['compro']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

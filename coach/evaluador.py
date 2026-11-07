"""Evaluador: rejuega compras reales de Abrams y mide el acierto del motor.

Es el juez del bucle de mejora: cada cambio de pesos o de reglas se mide aquí,
contra partidas reales, no contra intuición.
"""
import json, os, urllib.parse, urllib.request

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.deadlock-api.com"
SOLO_GANADAS = True
H = {"User-Agent": "abrams-coach/1.0", "Accept": "application/json"}


def _get(path, **q):
    u = API + path + ("?" + urllib.parse.urlencode(q) if q else "")
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=120) as r:
                return json.load(r)
        except Exception:
            if i == 2:
                return None


def descargar(cuantas, ruta=None):
    ruta = ruta or os.path.join(DIR, "data", "replay_cache.json")
    cache = json.load(open(ruta)) if os.path.exists(ruta) else []
    vistos = {c["match_id"] for c in cache}
    if len(cache) >= cuantas:
        return cache[:cuantas]
    for m in _get("/v1/matches/recently-fetched") or []:
        if len(cache) >= cuantas:
            break
        mid = m["match_id"]
        if mid in vistos:
            continue
        d = _get(f"/v1/matches/{mid}/metadata", include_player_info="true")
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
            "yo": {"slot": p["player_slot"], "team": p["team"],
                   "items": [{"t": it["game_time_s"], "id": str(it["item_id"]),
                              "vendido": it.get("sold_time_s") or 0} for it in p["items"]],
                   "stats": [{"t": s["time_stamp_s"], "neto": s["net_worth"]} for s in p["stats"]]},
            "jugadores": [{"slot": x["player_slot"], "team": x["team"], "hero": x["hero_id"]}
                          for x in mi.get("players", [])],
            "gane": mi.get("winning_team") == p["team"],
        })
        vistos.add(mid)
        json.dump(cache, open(ruta, "w"))
    return cache[:cuantas]


def _almas(stats, t):
    if not stats:
        return None
    if t <= stats[0]["t"]:
        return stats[0]["neto"]
    for a, b in zip(stats, stats[1:]):
        if a["t"] <= t <= b["t"]:
            return int(a["neto"] + (t-a["t"])/max(1, b["t"]-a["t"])*(b["neto"]-a["neto"]))
    return stats[-1]["neto"]


def construir_casos(partidas, conoc, cat, desde_min=10):
    """Lista de (estado, item_comprado) a partir de compras reales.

    El oro disponible se reconstruye como patrimonio menos lo ya gastado. Es una
    estimación: solo se conservan las compras donde el oro estimado alcanzaba, y la
    cobertura se reporta para no maquillar el resultado.
    """
    heroes = {k: v["nombre"].lower().replace(" ", "_")
              for k, v in json.load(open(os.path.join(DIR, "data", "heroes.json"))).items()}
    cat_items = set(conoc["items"])
    def costo(iid):
        return (cat.get(iid) or {}).get("costo") or 0
    casos, descartados = [], 0
    for p in partidas:
        if SOLO_GANADAS and not p.get("gane"):
            continue
        yo = p["yo"]
        compras = [i for i in yo["items"] if i["t"] >= desde_min*60 and i["id"] in cat_items]
        for c in compras:
            t = c["t"]
            patrimonio = _almas(yo["stats"], t)
            if patrimonio is None:
                continue
            # solo ítems que el motor conoce: los sin datos no ocupan slot en la simulación
            propios = [i["id"] for i in yo["items"]
                       if i["t"] <= t and (not i["vendido"] or i["vendido"] > t)
                       and i["id"] in cat_items]
            gastado = sum(costo(i) for i in propios)
            almas = max(0, patrimonio - gastado)
            if almas < costo(c["id"]):
                descartados += 1
                continue
            enemigos = [{"heroe": heroes.get(str(j["hero"]), str(j["hero"]))}
                        for j in p["jugadores"] if j["team"] != yo["team"]]
            if not enemigos:
                continue
            casos.append(({"t": t, "yo": {"heroe": "Abrams", "almas": almas, "items": propios},
                           "enemigos": enemigos, "aliados": [], "confianza": 1.0,
                           "fuente": "replay"}, c["id"]))
    casos_cobertura = (len(casos), len(casos) + descartados)
    return casos, casos_cobertura


def evaluar(casos, motor, cfg=None):
    """Devuelve (top1, top3, n) en fracción."""
    if cfg:
        motor.cfg = dict(motor.cfg)
        motor.cfg.update(cfg)
    a1 = a3 = n = 0
    for estado, comprado in casos:
        r = motor.analizar_dict(estado)
        ids = [x["id"] for x in r["recomendaciones"]]
        n += 1
        if ids and ids[0] == comprado:
            a1 += 1
        if comprado in ids:
            a3 += 1
    return (a1/n if n else 0, a3/n if n else 0, n)

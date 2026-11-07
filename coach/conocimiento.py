"""Construye la base de conocimiento: lift residual, pares, ventas y counters."""
import json, math, os, sys, time, urllib.parse, urllib.request

BASE = "https://api.deadlock-api.com"
DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(DIR, "data")
HERO = 6  # Abrams
MIN_ITEMS = 200        # muestra mínima por ítem
MIN_PAIRS = 15000       # muestra mínima por par
MIN_COUNTER = 800       # muestra mínima por ítem dentro de un matchup

def get(path, **params):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for i in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "abrams-coach/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except Exception as e:
            if i == 3:
                print(f"  ! {path} {params}: {getattr(e,'code',e)}", file=sys.stderr)
                return None
            time.sleep(3 * (i + 1))

def wilson(w, n, z=1.96):
    if not n: return (0.0, 0.0)
    p = w / n
    d = 1 + z*z/n
    c = p + z*z/(2*n)
    m = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return ((c-m)/d, (c+m)/d)

def construir_flujo(cat, items, MIN_N=20000):
    """Grafo real de orden de compra: qué se compra en cada fase y qué sigue después."""
    ruta = os.path.join(DATA, "flujo.json")
    if not os.path.exists(ruta):
        return {"fases": {}, "apertura": [], "siguiente": {}}
    d = json.load(open(ruta))
    nodos, aristas = d.get("nodes", []), d.get("edges", [])

    fases = {}
    for col in sorted({n["column"] for n in nodos}):
        fila = [n for n in nodos if n["column"] == col and n["matches"] >= MIN_N]
        fila.sort(key=lambda n: -n["adjusted_win_rate"])
        fases[str(col)] = [{
            "id": str(n["item_id"]),
            "nombre": cat.get(str(n["item_id"]), {}).get("nombre", str(n["item_id"])),
            "wr_ajustado": round(n["adjusted_win_rate"], 4),
            "n": n["matches"],
            "almas_compra": round(n.get("avg_net_worth_at_buy") or 0),
        } for n in fila[:24]]

    apertura = [n for n in nodos if n["column"] == 0 and n["matches"] >= 50000
                and (n.get("avg_net_worth_at_buy") or 0) < 2500]
    apertura.sort(key=lambda n: -n["adjusted_win_rate"])
    apertura = [{"id": str(n["item_id"]),
                 "nombre": cat.get(str(n["item_id"]), {}).get("nombre", "?"),
                 "wr_ajustado": round(n["adjusted_win_rate"], 4),
                 "n": n["matches"]} for n in apertura[:10]]

    por_origen = {}
    for e in aristas:
        if e["matches"] < 5000:
            continue
        por_origen.setdefault(str(e["from_item_id"]), []).append(
            {"id": str(e["to_item_id"]),
             "nombre": cat.get(str(e["to_item_id"]), {}).get("nombre", "?"),
             "n": e["matches"],
             "wr": round(e["wins"]/e["matches"], 4)})
    siguiente = {}
    for origen, lista in por_origen.items():
        lista.sort(key=lambda x: -x["n"])
        siguiente[origen] = lista[:5]

    return {"fases": fases, "apertura": apertura, "siguiente": siguiente,
            "fase_intervalo_s": 600}


def construir(forzar=False):
    ruta = os.path.join(DATA, "conocimiento.json")
    parcial = os.path.join(DATA, "conocimiento.parcial.json")
    recalcular = "--recalcular" in sys.argv
    if os.path.exists(ruta) and not forzar and not recalcular:
        return json.load(open(ruta))

    cat = json.load(open(os.path.join(DATA, "catalogo.json")))
    hs = json.load(open(os.path.join(DATA, "hero-stats.json")))[0]
    base = hs["wins"] / hs["matches"]
    istats = json.load(open(os.path.join(DATA, "item-stats.json")))

    # ---------- 1. ajuste por tiempo de compra ----------
    pts = [(r["avg_buy_time_relative"], r["wins"]/r["matches"] - base)
           for r in istats if r["matches"] >= MIN_ITEMS and r.get("avg_buy_time_relative")]
    n = len(pts)
    mx = sum(p[0] for p in pts)/n; my = sum(p[1] for p in pts)/n
    cov = sum((a-mx)*(b-my) for a, b in pts)/n
    var = sum((a-mx)**2 for a, b in pts)/n
    pend = cov/var if var else 0.0
    inter = my - pend*mx
    r2 = (cov*cov)/(var*(sum((b-my)**2 for a, b in pts)/n)) if var else 0.0

    items = {}
    for r in istats:
        iid = str(r["item_id"]); m = r["matches"]
        if m < MIN_ITEMS:
            continue
        wr = r["wins"]/m
        lift = wr - base
        t = r.get("avg_buy_time_relative")
        esperado_lift = inter + pend*t if t else inter
        lo, hi = wilson(r["wins"], m)
        d = cat.get(iid, {})
        sold = r.get("sold") or 0
        items[iid] = {
            "nombre": d.get("nombre", iid),
            "costo": d.get("costo", 0),
            "slot": d.get("slot"),
            "tier": d.get("tier"),
            "n": m,
            "winrate": round(wr, 5),
            "lift": round(lift, 5),
            # contracción por muestra: con pocas partidas el lift se acerca a cero
            "lift_residual": round((lift - esperado_lift) * (m / (m + 4000.0)), 5),
            "ic95": [round(lo, 5), round(hi, 5)],
            "min_compra": round(t, 2) if t else None,
            "min_venta": round(r.get("avg_sell_time_relative"), 2) if r.get("avg_sell_time_relative") else None,
            "veces_vendido": sold,
            "tasa_venta": round(sold/m, 4) if m else 0,
        }

    # ---------- 2. pares ----------
    pares = []
    for r in json.load(open(os.path.join(DATA, "perm-2.json"))):
        if r["matches"] < MIN_PAIRS:
            continue
        a, b = (str(x) for x in r["item_ids"])
        if a not in items or b not in items:
            continue
        wr = r["wins"]/r["matches"]
        lo, hi = wilson(r["wins"], r["matches"])
        pares.append({
            "a": a, "b": b, "n": r["matches"],
            "winrate": round(wr, 5),
            "lift": round(wr - base, 5),
            "ic95": [round(lo, 5), round(hi, 5)],
            "costo": items[a]["costo"] + items[b]["costo"],
        })
    pares.sort(key=lambda p: -p["lift"])

    # ---------- 3. counters por héroe enemigo ----------
    solo_recalcular = "--recalcular" in sys.argv
    counters = {}
    if os.path.exists(parcial):
        counters = json.load(open(parcial)).get("counters", {})
    hc = json.load(open(os.path.join(DATA, "counters.json")))
    enemigos = sorted({r["enemy_hero_id"] for r in hc if r.get("enemy_hero_id")})
    print(f"  counters: {len(enemigos)} héroes enemigos, ya tengo {len(counters)}")
    for i, eid in enumerate(enemigos):
        if solo_recalcular or str(eid) in counters:
            continue
        rows = get("/v1/analytics/item-stats", hero_id=HERO, enemy_hero_ids=eid)
        if not rows:
            continue
        d = {}
        for r in rows:
            if r["matches"] < MIN_COUNTER:
                continue
            iid = str(r["item_id"])
            base_e = None
            d[iid] = {"n": r["matches"], "winrate": round(r["wins"]/r["matches"], 5)}
        counters[str(eid)] = d
        if i % 10 == 0:
            json.dump({"counters": counters}, open(parcial, "w"))
            print(f"    {i+1}/{len(enemigos)}", flush=True)
        time.sleep(0.3)
    json.dump({"counters": counters}, open(parcial, "w"))

    # normalizar el counter contra el winrate de Abrams EN ESE matchup, no contra el global:
    # así se aísla "este ítem ayuda contra este héroe" de "este matchup ya era bueno".
    matchup_base = {str(r["enemy_hero_id"]): round(r["wins"]/r["matches_played"], 5)
                    for r in hc if r.get("enemy_hero_id")}
    for eid, d in counters.items():
        base_e = matchup_base.get(str(eid), base)
        for iid, v in d.items():
            v["delta"] = round(v["winrate"] - base_e, 5)

    salida = {
        "generado": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "heroe": "Abrams",
        "hero_id": HERO,
        "partidas_base": hs["matches"],
        "winrate_base": round(base, 5),
        "regresion": {"pendiente": round(pend, 6), "intercepto": round(inter, 6), "r2": round(r2, 4), "n": n},
        "items": items,
        "pares": pares[:400],
        "counters": counters,
        "matchup_base": matchup_base,
        "flujo": construir_flujo(cat, items),
        "heroes_index": json.load(open(os.path.join(DATA, "heroes_index.json")))
                        if os.path.exists(os.path.join(DATA, "heroes_index.json")) else {},
    }
    json.dump(salida, open(ruta, "w"), ensure_ascii=False)
    return salida


if __name__ == "__main__":
    k = construir(forzar="--forzar" in sys.argv)
    print(f"ítems: {len(k['items'])} · pares: {len(k['pares'])} · counters: {len(k['counters'])}")
    print(f"regresión: r2={k['regresion']['r2']} pendiente={k['regresion']['pendiente']}")

#!/usr/bin/env python3
"""Minería de patrones de Abrams sobre deadlock-api. Sin dependencias externas."""
import json, os, sys, time, math, urllib.request, urllib.parse

# Este script vive en herramientas/datos/: la raíz del repo está 3
# niveles arriba, no en el directorio del archivo.
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "https://api.deadlock-api.com"
DIR = RAIZ
DATA = os.path.join(DIR, "data")
HERO = 6  # Abrams

def get(path, **params):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for intento in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "abrams-coach/0.1", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except Exception as e:
            if intento == 2:
                print(f"  ! falló {path} {params}: {getattr(e,'code',e)}", file=sys.stderr)
                return None
            time.sleep(2 * (intento + 1))

def guardar(nombre, obj):
    with open(os.path.join(DATA, nombre), "w") as f:
        json.dump(obj, f, ensure_ascii=False)

def cargar(nombre):
    p = os.path.join(DATA, nombre)
    return json.load(open(p)) if os.path.exists(p) else None

print("== assets ==")
items = get("/v1/assets/items")
upg = {i["id"]: i for i in items if i.get("type") == "upgrade"}
guardar("items.json", upg)
print(f"  {len(upg)} ítems de tienda")

print("== baseline Abrams ==")
hs = get("/v1/analytics/hero-stats", hero_id=HERO)
guardar("hero-stats.json", hs)
base = hs[0]["wins"] / hs[0]["matches"]
print(f"  {hs[0]['matches']:,} partidas · winrate {base*100:.2f}%")

print("== items de Abrams ==")
istats = get("/v1/analytics/item-stats", hero_id=HERO)
guardar("item-stats.json", istats)
print(f"  {len(istats)} ítems con datos")

for comb in (2, 3):
    print(f"== combinaciones de {comb} ítems ==")
    p = get("/v1/analytics/item-permutation-stats", hero_id=HERO, comb_size=comb,
            min_matches=150 if comb == 2 else 60)
    guardar(f"perm-{comb}.json", p)
    print(f"  {len(p) if isinstance(p, list) else p} combinaciones")

print("== builds ==")
b = get(f"/v1/analytics/hero-build-stats/{HERO}", min_matches=150)
guardar("builds.json", b)
print(f"  {len(b) if isinstance(b, list) else b} builds")

print("== orden de habilidades ==")
ab = get("/v1/analytics/ability-order-stats", hero_id=HERO)
guardar("ability-order.json", ab)
print("  ok")

print("== counters ==")
hc = get("/v1/analytics/hero-counter-stats", hero_id=HERO)
guardar("counters.json", hc)
print(f"  {len(hc) if isinstance(hc, list) else hc} filas")

print("\nLISTO. Archivos en data/")

"""Catálogo de ítems de Deadlock normalizado desde deadlock-api."""
import json, os, urllib.request

BASE = "https://api.deadlock-api.com"
DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(DIR, "data")

def _get(path, **params):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "abrams-coach/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)

import urllib.parse


def construir(forzar=False):
    ruta = os.path.join(DATA, "catalogo.json")
    if os.path.exists(ruta) and not forzar:
        return json.load(open(ruta))

    crudo = _get("/v1/assets/items")
    cat = {}
    for it in crudo:
        if it.get("type") != "upgrade":
            continue
        cat[str(it["id"])] = {
            "id": it["id"],
            "nombre": it.get("name"),
            "costo": it.get("cost") or 0,
            "slot": it.get("item_slot_type"),
            "tier": it.get("item_tier"),
            "comprable": bool(it.get("shopable", True)),
            "activo": bool(it.get("is_active_item")),
            "mejora_a": list(it.get("upgrades") or []),      # en qué se convierte
            "icono": it.get("shop_image_webp") or it.get("shop_image"),
            "descripcion": (it.get("description") or {}).get("desc") if isinstance(it.get("description"), dict) else None,
        }
    # grafo inverso: de qué está hecho
    for iid, d in cat.items():
        d["viene_de"] = []
    for iid, d in cat.items():
        for destino in d["mejora_a"]:
            if str(destino) in cat:
                cat[str(destino)]["viene_de"].append(d["id"])

    json.dump(cat, open(ruta, "w"), ensure_ascii=False)
    return cat


def cargar():
    return construir()


if __name__ == "__main__":
    c = construir(forzar=True)
    print(f"{len(c)} ítems · slots: {sorted({d['slot'] for d in c.values() if d['slot']})}")
    print(f"tiers: {sorted({d['tier'] for d in c.values() if d['tier']})}")

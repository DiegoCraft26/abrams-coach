#!/usr/bin/env python3
"""Investigación de candidatos del meta: ¿este ítem gana por sí solo o por el combo?

El problema de mirar combinaciones es que un par puede brillar porque uno de sus dos
ítems ya gana solo. Aquí se descompone:

    winrate(ítem)        lo que gana el ítem por su cuenta
    winrate(par)         lo que gana con cada socio
    ventaja_socio        par − mejor socio individual   ← esto es lo que aporta el par

Si `ventaja_socio` ≈ 0, el combo no es sinergia: es el ítem arrastrando.

Cohortes para separar señal de sesgo:
    todos       45 días, sin filtro de oro
    pobres      max_networth 25000 (los que terminaron con poco: remontadas)
    reciente    14 días (parche actual)

Los datos se cachean en `data/api_cache/` para no repetir descargas.

Uso:
    python3 herramientas/investigar.py
    python3 herramientas/investigar.py --candidato "Scourge" --cohorte pobres
    python3 herramientas/investigar.py --combo 3 --min-matches 300
"""
import argparse
import hashlib
import json
import math
import os
import sys
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

API = "https://api.deadlock-api.com"
HEROE = 6
CACHE = os.path.join(RAIZ, "data", "api_cache")
H = {"User-Agent": "abrams-coach/1.0", "Accept": "application/json"}

COHORTES = {
    "todos": {},
    "pobres": {"max_networth": 25000},
    "reciente": {"dias": 14},
}


def _get(ruta, params, cachear=True, forzar=False):
    clave = hashlib.sha1((ruta + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:16]
    ruta_cache = os.path.join(CACHE, clave + ".json")
    if cachear and not forzar and os.path.exists(ruta_cache):
        with open(ruta_cache, encoding="utf-8") as f:
            return json.load(f)
    url = API + ruta + "?" + urllib.parse.urlencode(params)
    for intento in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=H),
                                        timeout=180) as r:
                datos = json.load(r)
            if cachear:
                os.makedirs(CACHE, exist_ok=True)
                with open(ruta_cache, "w", encoding="utf-8") as f:
                    json.dump(datos, f)
            return datos
        except Exception:
            if intento == 2:
                raise
    return None


def wilson(v, n, z=1.96):
    if n <= 0:
        return 0.0
    p = v / n
    den = 1 + z * z / n
    centro = p + z * z / (2 * n)
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centro - margen) / den


def nombres():
    salida = {}
    try:
        items = json.load(open(os.path.join(RAIZ, "data", "items.json"), encoding="utf-8"))
        for iid, d in items.items():
            salida[str(iid)] = d.get("name") or d.get("nombre") or str(iid)
    except Exception:                                        # noqa: BLE001
        pass
    return salida


def costes():
    salida = {}
    try:
        items = json.load(open(os.path.join(RAIZ, "data", "items.json"), encoding="utf-8"))
        for iid, d in items.items():
            if d.get("cost"):
                salida[str(iid)] = int(d["cost"])
    except Exception:                                        # noqa: BLE001
        pass
    return salida


def params_cohorte(cohorte, combo, min_matches):
    p = {"hero_id": HEROE, "comb_size": combo, "min_matches": min_matches}
    extra = COHORTES[cohorte]
    if "max_networth" in extra:
        p["max_networth"] = extra["max_networth"]
    if "dias" in extra and extra["dias"]:
        import time
        p["min_unix_timestamp"] = int(time.time()) - extra["dias"] * 86400
    return p


def item_stats(cohorte):
    extra = {}
    c = COHORTES[cohorte]
    if "max_networth" in c:
        extra["max_networth"] = c["max_networth"]
    if "dias" in c:
        import time
        extra["min_unix_timestamp"] = int(time.time()) - c["dias"] * 86400
    try:
        filas = _get("/v1/analytics/item-stats",
                     {"hero_id": HEROE, "min_matches": 100, **extra})
        return {str(f["item_id"]): f for f in filas}
    except Exception:                                        # noqa: BLE001
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidato", action="append", default=None,
                    help="ítem por nombre (repetible). Por defecto, la lista del informe")
    ap.add_argument("--cohorte", default="todos", choices=sorted(COHORTES))
    ap.add_argument("--combo", type=int, default=2)
    ap.add_argument("--min-matches", type=int, default=200)
    ap.add_argument("--forzar", action="store_true", help="ignora la caché de la API")
    ap.add_argument("--salida", default=None)
    a = ap.parse_args()

    nom = nombres()
    coste = costes()
    cand_nombres = a.candidato or ["Scourge", "Frenzy", "Magic Carpet", "Colossus",
                                   "Metal Skin", "Return Fire", "Superior Duration",
                                   "Bullet Resist Shredder"]
    # nombre -> id
    por_nombre = {}
    for iid, n in nom.items():
        por_nombre.setdefault(n.lower(), iid)
    ids = {}
    for n in cand_nombres:
        iid = por_nombre.get(n.lower())
        if iid:
            ids[iid] = n
        else:
            print(f"  (no encuentro '{n}' en el catálogo)")

    p = params_cohorte(a.cohorte, a.combo, a.min_matches)
    print(f"descargando combos · héroe {HEROE} · tamaño {a.combo} · cohorte {a.cohorte} · "
          f"muestra mínima {a.min_matches}")
    try:
        combos = _get("/v1/analytics/item-permutation-stats", p, forzar=a.forzar)
    except Exception:                                        # noqa: BLE001
        print("sin datos de la API (¿red?). No se tocó nada.")
        return 2
    print(f"combos: {len(combos)}")

    stats = item_stats(a.cohorte)
    base = None
    try:
        hs = _get("/v1/analytics/hero-stats", {k: v for k, v in p.items()
                                               if k in ("min_unix_timestamp",
                                                        "max_networth")})
        base = hs[0]["wins"] / max(1, hs[0]["wins"] + hs[0]["losses"])
    except Exception:                                        # noqa: BLE001
        pass
    print(f"winrate base de Abrams en la cohorte: "
          f"{'—' if base is None else f'{base:.1%}'}")

    def wr_item(iid):
        f = stats.get(str(iid))
        if not f or not f.get("matches"):
            return None
        return wilson(f["wins"], f["matches"])

    print(f"\n{'ítem':24} {'n':>9} {'wr':>7} {'lcb':>7} {'pares':>6} "
          f"{'mejor par':>10} {'ventaja socio':>14}")
    informe = []
    for iid, nombre in ids.items():
        pares = [c for c in combos if str(iid) in [str(x) for x in c["item_ids"]]]
        if not pares:
            print(f"{nombre:24} (sin pares)")
            continue
        mejor = max(pares, key=lambda c: c["wins"] / max(1, c["matches"]))
        socio = [str(x) for x in mejor["item_ids"] if str(x) != str(iid)][0]
        wr_par = mejor["wins"] / max(1, mejor["matches"])
        wr_socio = wr_item(socio)
        ventaja = (wr_par - wr_socio) if wr_socio is not None else None
        propio = wr_item(iid)
        n_total = sum(c["matches"] for c in pares)
        informe.append({
            "item": iid, "nombre": nombre, "n_pares": len(pares), "n_total": n_total,
            "wr": None if propio is None else round(propio, 4),
            "mejor_par": [nom.get(str(x), str(x)) for x in mejor["item_ids"]],
            "wr_par": round(wr_par, 4),
            "wr_socio": None if wr_socio is None else round(wr_socio, 4),
            "ventaja_socio": None if ventaja is None else round(ventaja, 4),
            "coste": coste.get(str(iid)),
        })
        print(f"{nombre:24} {n_total:>9,} "
              f"{'—' if propio is None else f'{propio:6.1%}'} "
              f"{'—' if propio is None else f'{propio:7.1%}'} {len(pares):>6} "
              f"{'+'.join(nom.get(str(x), str(x))[0:12] for x in mejor['item_ids']):>10} "
              f"{'—' if ventaja is None else f'{ventaja*100:+13.2f} pp'}")

    ruta = a.salida or os.path.join(RAIZ, "salida", "investigacion",
                                    f"candidatos-{a.cohorte}-c{a.combo}.json")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"cohorte": a.cohorte, "combo": a.combo, "base": base,
                   "candidatos": informe}, f, ensure_ascii=False, indent=1)
    print(f"\nJSON: {os.path.relpath(ruta, RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

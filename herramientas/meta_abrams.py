#!/usr/bin/env python3
"""Meta de Abrams a partir de las partidas que ya tenemos, no de una guía.

`data/heroes/abrams.json` dice que la apertura es Restorative Shot, y 626 partidas reales
de Abrams dicen que lo que de verdad se compra antes del minuto 10 es Extra Regen,
Duration Extender y Spirit Strike. Esta herramienta saca eso del cache y lo deja en
`data/meta_abrams.json`, con su muestra y su fecha, para que el camino de build use el
meta observado y no una lista de una web.

Uso:
    python3 herramientas/meta_abrams.py
    python3 herramientas/meta_abrams.py --top 12 --salida data/meta_abrams.json
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

CACHE = os.path.join(RAIZ, "data", "replay_cache.json")
CONOC = os.path.join(RAIZ, "data", "conocimiento.json")


def tramo(t):
    if t < 600:
        return "0-10"
    if t < 1200:
        return "10-20"
    if t < 1800:
        return "20-30"
    return "30+"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--salida", default=os.path.join(RAIZ, "data", "meta_abrams.json"))
    a = ap.parse_args()

    conoc = json.load(open(CONOC, encoding="utf-8"))
    items = conoc["items"]
    with open(CACHE, encoding="utf-8") as f:
        partidas = json.load(f)

    # Un ítem que no sube a nada (Extra Regen) no es una pieza de build: es un gasto que
    # se queda ahí. Diego lo señaló el 2026-11-10 y los datos lo confirman: Extra Regen
    # no compone ningún ítem del catálogo. Se pondera por «progresa», pero sin borrarlo:
    # ser barato y comprarse mucho sigue siendo información (0.60, no 0).
    try:
        comp = json.load(open(os.path.join(RAIZ, "data", "componentes.json"), encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        comp = {}
    progresa = set()
    for padre, hijos in comp.items():
        for h in hijos:
            progresa.add(str(h))

    cuenta = Counter()
    por_tramo = defaultdict(Counter)
    primera = Counter()          # primera compra real de cada partida
    partidas_con = 0
    for p in partidas:
        compras = [i for i in p["yo"]["items"] if i["id"] in items]
        if not compras:
            continue
        partidas_con += 1
        primera[compras[0]["id"]] += 1
        for c in compras:
            cuenta[c["id"]] += 1
            por_tramo[tramo(c["t"])][c["id"]] += 1

    def ficha(iid):
        return {"id": iid, "nombre": items[iid].get("nombre", iid),
                "costo": items[iid].get("costo") or 0}

    def peso_progreso(iid):
        return 1.0 if str(iid) in progresa else 0.60

    ranking = sorted(
        ((iid, n * peso_progreso(iid)) for iid, n in cuenta.items()
         if (items[iid].get("costo") or 0) <= 800),
        key=lambda kv: -kv[1])
    apertura = [ficha(iid) for iid, _ in ranking[:5]]
    salida = {
        "generado": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "fuente": "data/replay_cache.json",
        "partidas": partidas_con,
        "apertura": [x["id"] for x in apertura],
        "apertura_detalle": [dict(x, progresa=str(x["id"]) in progresa) for x in apertura],
        "primera_compra": [{"id": iid, "nombre": items[iid].get("nombre", iid),
                            "partidas": n} for iid, n in primera.most_common(6)],
        "tramos": {k: [{"id": iid, "nombre": items[iid].get("nombre", iid),
                        "n": n} for iid, n in v.most_common(a.top)]
                   for k, v in por_tramo.items()},
    }
    os.makedirs(os.path.dirname(a.salida), exist_ok=True)
    with open(a.salida, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)

    print(f"meta de Abrams · {partidas_con} partidas con compras conocidas")
    print("apertura observada:", [(x["nombre"], x["costo"]) for x in apertura])
    print("primera compra más común:",
          [(x["nombre"], x["partidas"]) for x in salida["primera_compra"]])
    for k in ("0-10", "10-20", "20-30", "30+"):
        print(f"  {k:5}", [(x["nombre"], x["n"]) for x in salida["tramos"].get(k, [])[:6]])
    print("escrito en", os.path.relpath(a.salida, RAIZ))
    return 0


if __name__ == "__main__":
    sys.exit(main())

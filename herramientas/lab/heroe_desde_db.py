#!/usr/bin/env python3
"""Apertura de un héroe medida en la base, no copiada de una guía.

El motor ya lee `data/heroes/<clave>.json` y cae a Abrams si falta. Hasta hoy solo había
Abrams porque sus datos venían de una guía. Esto deriva **solo la apertura** de lo que la
base mide: los cinco ítems más comprados en los primeros diez minutos.

Lo que **no** deriva, y por eso el JSON no los lleva: los hitos de almas y las fases. Para
Abrams salen de una guía con fuente y fecha; para otro héroe no hay fuente equivalente, y
`coach/decision/heroe.py` ya tiene un respaldo por si faltan. Inventar umbrales de almas
para un héroe que no se midió sería peor que usar el respaldo y decirlo.

Uso:
    python3 herramientas/lab/heroe_desde_db.py --heroe 13
    python3 herramientas/lab/heroe_desde_db.py --heroe 84 --min-partidas 200 --guardar
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(RAIZ, "datos", "lab.db")
SALIDA = os.path.join(RAIZ, "data", "heroes")
CORTE_APERTURA_S = 600          # primeros 10 minutos


def _slug(nombre: str) -> str:
    return "".join(c for c in nombre.lower() if c.isalnum())


def nombre_de(heroe: int) -> str | None:
    for ruta in (os.path.join(RAIZ, "data", "heroes.json"),
                 os.path.join(RAIZ, "data", "heroes_index.json")):
        try:
            doc = json.load(open(ruta, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        datos = doc.get(str(heroe)) if isinstance(doc, dict) else None
        if isinstance(datos, dict) and datos.get("nombre"):
            return str(datos["nombre"])
    return None


def apertura(heroe: int, db: str = DB, corte: int = CORTE_APERTURA_S,
             cuantos: int = 5, min_partidas: int = 150) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        filas = con.execute("""
            SELECT c.item_id, COUNT(*) AS n, COUNT(DISTINCT c.match_id) AS partidas
            FROM compras_api c
            JOIN jugadores_api j ON j.match_id = c.match_id
                                AND j.player_slot = c.player_slot
            WHERE j.hero_id = ? AND c.t <= ?
            GROUP BY c.item_id
            ORDER BY n DESC
            LIMIT ?
        """, (int(heroe), int(corte), int(cuantos))).fetchall()
        total = con.execute("""
            SELECT COUNT(DISTINCT j.match_id) FROM jugadores_api j WHERE j.hero_id = ?
        """, (int(heroe),)).fetchone()[0]
    finally:
        con.close()
    if total < min_partidas or not filas:
        return {"items": [], "n_partidas": int(total), "n_compras": 0,
                "suficiente": False}
    return {"items": [str(f[0]) for f in filas],
            "n_partidas": int(total),
            "n_compras": int(sum(f[1] for f in filas)),
            "suficiente": True}


def construir(heroe: int, db: str = DB, min_partidas: int = 150) -> dict:
    nombre = nombre_de(heroe) or f"héroe {heroe}"
    ap = apertura(heroe, db=db, min_partidas=min_partidas)
    doc = {
        "id": int(heroe),
        "nombre": nombre,
        "clave": _slug(nombre),
        "apertura": {
            "items": ap["items"],
            "fuente": (f"datos/lab.db: {ap['n_compras']} compras en los primeros "
                       f"{CORTE_APERTURA_S // 60} min, {ap['n_partidas']} partidas"),
            "fecha": date.today().isoformat(),
        },
        "notas": ("Apertura medida en la base. Hitos de almas y fases no se derivan: usan "
                  "el respaldo de Abrams hasta que haya una fuente medida por héroe."),
    }
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Apertura por héroe desde lab.db")
    ap.add_argument("--heroe", type=int, required=True)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--min-partidas", type=int, default=150)
    ap.add_argument("--guardar", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    doc = construir(a.heroe, db=a.db, min_partidas=a.min_partidas)
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        ap_ = doc["apertura"]
        print(f"{doc['nombre']} ({doc['clave']}, id {doc['id']}): "
              f"{len(ap_['items'])} ítems de apertura · {ap_['fuente']}")
        print("  " + ", ".join(ap_["items"]))
    if a.guardar:
        if not doc["apertura"]["items"]:
            print("sin muestra suficiente: no se guarda", file=sys.stderr)
            return 2
        os.makedirs(SALIDA, exist_ok=True)
        ruta = os.path.join(SALIDA, f"{doc['clave']}.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print(f"guardado en {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

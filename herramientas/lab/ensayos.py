#!/usr/bin/env python3
"""Ensayos sobre las compras reales: preguntas que el motor no puede formular.

Cada ensayo compara un subgrupo contra la línea base (el WR del propio conjunto) y
guarda n, efecto en puntos, intervalo de Wilson al 95% y veredicto. La regla es dura a
propósito: si el intervalo incluye la línea base, el veredicto es «sin evidencia»,
aunque el número se vea bonito. Con 626 partidas casi todo va a salir «sin evidencia»;
eso es el resultado, no un fallo.

Los ensayos caben en tres familias:
    A · apertura     qué se compra primero y a qué costo
    B · ritmo        cuándo se llega a los tramos de precio
    C · composición  cuántos ítems de cada tipo y cuántos baratos aguanta la partida

Uso:
    python3 herramientas/lab/ensayos.py
    python3 herramientas/lab/ensayos.py --listar
    python3 herramientas/lab/ensayos.py --json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from herramientas.lab import db  # noqa: E402

Z = 1.959963984540054  # 95 %


def wilson(ganadas, n):
    """Intervalo de Wilson para una proporción. Con n=0 devuelve (0, 1)."""
    if n <= 0:
        return 0.0, 1.0
    p = ganadas / n
    den = 1 + Z * Z / n
    centro = (p + Z * Z / (2 * n)) / den
    mitad = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / den
    return max(0.0, centro - mitad), min(1.0, centro + mitad)


def veredicto(ic_bajo, ic_alto, base):
    if ic_bajo > base:
        return "mejor (significativo)"
    if ic_alto < base:
        return "peor (significativo)"
    return "sin evidencia"


def cargar(con):
    """{match_id: {"gane": 0/1, "compras": [(t, id, coste)]}}"""
    partidas = {}
    for r in con.execute("SELECT match_id, gane FROM partidas WHERE gane IS NOT NULL"):
        partidas[r["match_id"]] = {"gane": int(r["gane"]), "compras": []}
    for r in con.execute("SELECT match_id, t, item_id, coste FROM compras "
                         "ORDER BY match_id, orden"):
        p = partidas.get(r["match_id"])
        if p is not None:
            p["compras"].append((r["t"], r["item_id"], r["coste"] or 0))
    return {k: v for k, v in partidas.items() if len(v["compras"]) >= 3}


def base_wr(partidas):
    n = len(partidas)
    g = sum(1 for p in partidas.values() if p["gane"])
    return (g / n if n else 0.0), g, n


def ensayo(con, nombre, hipotesis, base, seleccion, datos=None):
    """`seleccion` recibe el diccionario de partida y devuelve True si entra."""
    dentro = [p for p in partidas_ref.values() if seleccion(p)]
    n = len(dentro)
    g = sum(1 for p in dentro if p["gane"])
    lo, hi = wilson(g, n)
    p = (g / n) if n else 0.0
    efecto = (p - base) * 100
    v = veredicto(lo, hi, base)
    db.guardar_ensayo(con, nombre, hipotesis, n, round(efecto, 2),
                      round(lo * 100, 2), round(hi * 100, 2), v,
                      json.dumps(datos or {}, ensure_ascii=False))
    return {"nombre": nombre, "hipotesis": hipotesis, "n": n, "wr": p,
            "efecto": efecto, "ic": (lo, hi), "veredicto": v}


partidas_ref = {}


def correr(con):
    global partidas_ref
    partidas_ref = cargar(con)
    base, g, n = base_wr(partidas_ref)
    if not n:
        print("no hay partidas con resultado en la base: corre ingesta.py primero")
        return []
    print(f"base: {n} partidas · WR {base:.1%}")
    salida = []

    def primera(p):
        return p["compras"][0]

    salida.append(ensayo(
        con, "apertura_800", "Abrir con un ítem de 800 late más que abrir con 1,600+",
        base, lambda p: primera(p)[2] <= 800,
        {"concepto": "A"}))

    salida.append(ensayo(
        con, "apertura_1600_mas", "Abrir con 1,600 o más (saltarse los 800) rinde",
        base, lambda p: primera(p)[2] >= 1600,
        {"concepto": "A"}))

    salida.append(ensayo(
        con, "sin_comprar_5min", "Aguantar sin comprar hasta el minuto 5 y guardar",
        base, lambda p: primera(p)[0] >= 300,
        {"concepto": "A"}))

    salida.append(ensayo(
        con, "caro_temprano", "Meter un 6,400 entre las tres primeras compras",
        base, lambda p: any(c >= 6400 for _, _, c in p["compras"][:3]),
        {"concepto": "B"}))

    def llega_3200_antes_12(p):
        for t, _, c in p["compras"]:
            if c >= 3200:
                return t <= 720
        return False

    salida.append(ensayo(
        con, "3200_antes_12", "Llegar a un 3,200+ antes del minuto 12",
        base, llega_3200_antes_12, {"concepto": "B"}))

    def muchos_800(p):
        return sum(1 for t, _, c in p["compras"] if c <= 800 and t <= 900) >= 4

    salida.append(ensayo(
        con, "cuatro_800_primeros_15", "Cuatro o más ítems de 800 en los primeros 15 min",
        base, muchos_800, {"concepto": "B"}))

    print()
    print(f"{'ensayo':24s} {'n':>5} {'WR':>7} {'efecto':>8} {'IC95':>16}  veredicto")
    for e in salida:
        lo, hi = e["ic"]
        print(f"{e['nombre']:24s} {e['n']:5d} {e['wr']:6.1%} "
              f"{e['efecto']:+7.1f}pp [{lo:5.1%},{hi:5.1%}]  {e['veredicto']}")
    return salida


def listar(con):
    filas = con.execute("SELECT * FROM ensayos ORDER BY id").fetchall()
    if not filas:
        print("todavía no hay ensayos guardados")
        return
    print(f"{'ensayo':24s} {'n':>6} {'efecto':>8}  veredicto")
    for r in filas:
        print(f"{r['nombre']:24s} {r['n']:6d} {r['efecto']:+7.1f}pp  {r['veredicto']}")


def main():
    ap = argparse.ArgumentParser(description="Laboratorio de compras")
    ap.add_argument("--db", default=db.RUTA)
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    con = db.conectar(args.db)
    db.crear_esquema(con)
    if args.listar:
        listar(con)
        return 0
    res = correr(con)
    con.commit()
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

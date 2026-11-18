#!/usr/bin/env python3
"""Residual de cada ítem controlando coste y minuto, por cohorte.

`lift_residual` de `data/conocimiento.json` ya hace esto sobre 1.9M de partidas, pero es
un número global. Aquí se recalcula para las cohortes que importan (pobre, partida de
30-40 min, parche reciente) para responder: «¿este ítem sigue rindiendo cuando solo miras
a los que van perdiendo?».

Modelo: logit(winrate) = a + b·log(coste) + c·minuto_de_compra, ajustado por mínimos
cuadrados ponderados por muestra. El residual es lo que el ítem gana por encima de lo que
le tocaría por ser caro y tardío. Sin dependencias: se resuelve un sistema 3×3 a mano.

Uso:
    python3 herramientas/residuales.py
    python3 herramientas/residuales.py --cohorte pobres --min-matches 200
    python3 herramientas/residuales.py --networth-max 25000 --dur 1800 2400
"""
import argparse
import importlib.util
import json
import math
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

_spec = importlib.util.spec_from_file_location(
    "investigar", os.path.join(RAIZ, "herramientas", "investigar.py"))
inv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inv)


def resolver(A, b):
    """Gauss para un sistema pequeño (3×3)."""
    n = len(A)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return None
        M[col], M[piv] = M[piv], M[col]
        for r in range(n):
            if r == col:
                continue
            f = M[r][col] / M[col][col]
            for k in range(col, n + 1):
                M[r][k] -= f * M[col][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def ajustar(puntos):
    """OLS ponderado: puntos = [(x1, x2, y, peso)] -> (a, b, c)."""
    A = [[0.0] * 3 for _ in range(3)]
    b = [0.0] * 3
    for x1, x2, y, w in puntos:
        fila = (1.0, x1, x2)
        for i in range(3):
            b[i] += w * fila[i] * y
            for j in range(3):
                A[i][j] += w * fila[i] * fila[j]
    coef = resolver(A, b)
    return coef or (0.0, 0.0, 0.0), A, b


def datos(cohorte, min_matches, networth_max=None, dur=None, desde=None, hasta=None):
    extra = {}
    if networth_max:
        extra["max_networth"] = networth_max
    if desde:
        extra["min_unix_timestamp"] = desde
    if hasta:
        extra["max_unix_timestamp"] = hasta
    if cohorte in inv.COHORTES and "dias" in inv.COHORTES[cohorte] and not desde:
        import time
        extra["min_unix_timestamp"] = int(time.time()) - inv.COHORTES[cohorte]["dias"] * 86400
    if dur:
        extra["min_duration_s"] = dur[0]
        extra["max_duration_s"] = dur[1]
    filas = inv._get("/v1/analytics/item-stats",
                     {"hero_id": 6, "min_matches": min_matches, **extra})
    hs = inv._get("/v1/analytics/hero-stats", {"hero_id": 6, **extra})
    base = hs[0]["wins"] / max(1, hs[0]["wins"] + hs[0]["losses"])
    return filas, base, extra


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohorte", default="todos")
    ap.add_argument("--min-matches", type=int, default=200)
    ap.add_argument("--networth-max", type=int, default=None)
    ap.add_argument("--dur", type=int, nargs=2, default=None, metavar=("MIN", "MAX"))
    ap.add_argument("--desde", default=None, help="AAAA-MM-DD (ventana de parche)")
    ap.add_argument("--hasta", default=None, help="AAAA-MM-DD")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--fuera", nargs="*", default=None,
                    help="ítems a mirar aparte (por nombre)")
    a = ap.parse_args()

    import datetime as _dt

    def _unix(f):
        return None if not f else int(_dt.datetime.strptime(f, "%Y-%m-%d")
                                       .replace(tzinfo=_dt.timezone.utc).timestamp())
    try:
        filas, base, extra = datos(a.cohorte, a.min_matches, a.networth_max, a.dur,
                                   _unix(a.desde), _unix(a.hasta))
    except Exception:                                        # noqa: BLE001
        print("sin datos de la API (¿red?). No se tocó nada.")
        return 2
    nom = inv.nombres()
    coste = inv.costes()

    puntos = []
    for f in filas:
        n = f["matches"]
        if n < a.min_matches:
            continue
        w, l = f["wins"], f["losses"]
        y = math.log((w + 0.5) / (l + 0.5))
        c = coste.get(str(f["item_id"]), 0) or 1
        t = (f.get("avg_buy_time_s") or 0) / 60.0
        puntos.append((math.log(c), t, y, math.sqrt(n)))
    if len(puntos) < 10:
        print("muestra insuficiente")
        return 1
    coef, _, _ = ajustar(puntos)
    a0, b1, b2 = coef

    resultado = []
    for f in filas:
        n = f["matches"]
        if n < a.min_matches:
            continue
        w, l = f["wins"], f["losses"]
        y = math.log((w + 0.5) / (l + 0.5))
        c = coste.get(str(f["item_id"]), 0) or 1
        t = (f.get("avg_buy_time_s") or 0) / 60.0
        pred = a0 + b1 * math.log(c) + b2 * t
        res = y - pred
        # de logit a puntos porcentuales (pendiente máxima de la logística en p≈0.5)
        resultado.append({
            "id": str(f["item_id"]),
            "nombre": nom.get(str(f["item_id"]), str(f["item_id"])),
            "n": n,
            "wr": round(w / max(1, w + l), 4),
            "coste": c,
            "minuto": round(t, 1),
            "residual_pp": round(res * 25.0, 2),
        })
    resultado.sort(key=lambda x: -x["residual_pp"])

    print(f"cohorte {a.cohorte} {extra} · base {base:.1%} · ítems {len(resultado)}")
    print(f"modelo: logit = {a0:.3f} + {b1:.3f}·log(coste) + {b2:.4f}·minuto")
    print(f"\nTOP {a.top} (residual, controlados coste y minuto):")
    for x in resultado[:a.top]:
        print(f"  {x['residual_pp']:+6.2f} pp  wr {x['wr']:5.1%}  n={x['n']:>8,}  "
              f"{x['coste']:>5} @ {x['minuto']:>4.1f}m  {x['nombre']}")
    print(f"\nPEORES {a.top}:")
    for x in resultado[-a.top:]:
        print(f"  {x['residual_pp']:+6.2f} pp  wr {x['wr']:5.1%}  n={x['n']:>8,}  "
              f"{x['coste']:>5} @ {x['minuto']:>4.1f}m  {x['nombre']}")

    if a.fuera:
        print("\ncandidatos:")
        for nombre in a.fuera:
            x = next((r for r in resultado if r["nombre"].lower() == nombre.lower()), None)
            if x:
                pos = resultado.index(x) + 1
                print(f"  {nombre:22} {x['residual_pp']:+6.2f} pp · puesto {pos}/{len(resultado)}"
                      f" · n={x['n']:,} · wr {x['wr']:.1%}")

    ruta = os.path.join(RAIZ, "salida", "investigacion",
                        f"residuales-{a.cohorte}{'-dur' if a.dur else ''}.json")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"cohorte": a.cohorte, "extra": extra, "base": base,
                   "modelo": {"a": a0, "log_coste": b1, "minuto": b2},
                   "items": resultado}, f, ensure_ascii=False, indent=1)
    print(f"\nJSON: {os.path.relpath(ruta, RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

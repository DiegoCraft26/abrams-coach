#!/usr/bin/env python3
"""Baja el historial de partidas de cada cuenta de la semilla, con caché y freno.

Por qué: `/v1/players/{account_id}/match-history` devuelve todo el historial guardado en
una sola petición (sin paginación) y trae los campos macro: `ranked_display_badge`,
`ranked_delta`, `ranked_calibration_match`, `ranked_used_demotion_protection`,
`low_pri_pool`, `abandoned_time_s`, `game_mode`, `match_mode`, `start_time`, héroe y KDA.
Es la única fuente que permite reconstruir la progresión de rango de una cuenta.

Reglas:
- caché en disco por cuenta: reanudable, un corte no pierde nada;
- ≤150 peticiones por ventana de 60 s y 0.45 s entre peticiones;
- un 429 con `Retry-After` se espera; si insiste 3 veces, la corrida **se detiene**
  (no se martilla la API);
- regiones por lote (`/v1/players/region`, hasta 1000 cuentas por petición) para poder
  pasar `start_time` a hora local.

Uso:
    python3 herramientas/macro/historial.py                 # toda la semilla, reanudando
    python3 herramientas/macro/historial.py --limite 60     # solo 60 cuentas esta corrida
    python3 herramientas/macro/historial.py --regiones      # solo el mapa de regiones
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (BASE, Freno, Presupuesto, escribir_json, leer_json,  # noqa: E402
                    traer)

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATOS = os.path.join(RAIZ, "datos", "macro")
SEMILLA = os.path.join(DATOS, "semilla.json")
CACHE_HIST = os.path.join(DATOS, "cache", "historial")
CACHE_REGION = os.path.join(DATOS, "cache", "regiones.json")
ESTADO = os.path.join(DATOS, "estado_descarga.json")
PRESUPUESTO = os.path.join(DATOS, "presupuesto.json")


def ruta_hist(acc):
    return os.path.join(CACHE_HIST, f"{acc}.json")


def bajar_historial(pres, acc):
    url = f"{BASE}/v1/players/{acc}/match-history"
    datos = traer(pres, url)
    if not isinstance(datos, list):
        raise RuntimeError(f"respuesta inesperada para {acc}: {type(datos).__name__}")
    escribir_json(ruta_hist(acc), datos)
    return len(datos)


def bajar_regiones(pres, cuentas):
    guardado = leer_json(CACHE_REGION, {}) or {}
    faltan = [a for a in cuentas if str(a) not in guardado]
    if not faltan:
        return guardado
    for i in range(0, len(faltan), 1000):
        lote = faltan[i:i + 1000]
        url = f"{BASE}/v1/players/region?{urlencode({'account_ids': ','.join(map(str, lote))})}"
        resp = traer(pres, url)
        for fila in resp or []:
            if isinstance(fila, dict) and fila.get("account_id") is not None:
                guardado[str(fila["account_id"])] = {
                    "region": fila.get("region"),
                    "region_month": fila.get("region_month"),
                }
        escribir_json(CACHE_REGION, guardado)
        print(f"  regiones: {len(guardado)} acumuladas", flush=True)
    return guardado


def main():
    ap = argparse.ArgumentParser(description="Baja match-history de la semilla")
    ap.add_argument("--semilla", default=SEMILLA)
    ap.add_argument("--limite", type=int, default=0, help="cuentas nuevas en esta corrida")
    ap.add_argument("--regiones", action="store_true", help="solo actualizar regiones")
    ap.add_argument("--solo-faltantes", action="store_true", default=True)
    args = ap.parse_args()

    semilla = leer_json(args.semilla)
    if not semilla:
        sys.exit(f"falta la semilla: {args.semilla} (corre semilla.py primero)")
    cuentas = [int(x["account_id"]) for x in semilla["muestra"]]
    os.makedirs(CACHE_HIST, exist_ok=True)
    pres = Presupuesto(PRESUPUESTO)

    estado = leer_json(ESTADO, {}) or {"ok": [], "fallidos": {}, "freno": None}
    estado.setdefault("ok", [])
    estado.setdefault("fallidos", {})

    print(f"semilla: {len(cuentas)} cuentas · ya en caché: "
          f"{sum(1 for a in cuentas if os.path.exists(ruta_hist(a)))}", flush=True)

    if not args.regiones:
        pendientes = [a for a in cuentas if not os.path.exists(ruta_hist(a))]
        if args.limite:
            pendientes = pendientes[:args.limite]
        print(f"a bajar: {len(pendientes)}", flush=True)
        try:
            for i, acc in enumerate(pendientes, 1):
                try:
                    n = bajar_historial(pres, acc)
                    estado["ok"].append(acc)
                    estado["fallidos"].pop(str(acc), None)
                    if i % 20 == 0 or i == len(pendientes):
                        print(f"  {i}/{len(pendientes)} · {acc}: {n} partidas · "
                              f"{pres.total} peticiones totales", flush=True)
                except Freno as e:
                    estado["freno"] = {"cuando": dt.datetime.now().isoformat(timespec="seconds"),
                                       "motivo": str(e), "cuenta": acc}
                    escribir_json(ESTADO, estado)
                    print(f"\nFRENO: {e}\nse detiene la corrida; reanuda más tarde con el "
                          f"mismo comando.", file=sys.stderr)
                    sys.exit(3)
                except RuntimeError as e:
                    estado["fallidos"][str(acc)] = str(e)[:300]
                    print(f"  fallo {acc}: {e}", file=sys.stderr)
                if i % 25 == 0:
                    escribir_json(ESTADO, estado)
        finally:
            escribir_json(ESTADO, estado)

    print("regiones…", flush=True)
    regs = bajar_regiones(pres, cuentas)
    con_region = sum(1 for a in cuentas if regs.get(str(a), {}).get("region"))
    print(f"regiones con dato: {con_region}/{len(cuentas)}")
    print(f"peticiones totales de la sesión: {pres.total}")


if __name__ == "__main__":
    main()

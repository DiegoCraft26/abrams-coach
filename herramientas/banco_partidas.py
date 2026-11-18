#!/usr/bin/env python3
"""Banco de partidas: corre el motor sobre todas las partidas del cache y saca números.

Responde a «¿esto aguanta fuera de las tres partidas que probé a mano?» y a «¿el coach
recomienda lo que de verdad compran los Abrams, o hay ítems sobre/infrautilizados?».

Qué mide, por muestra (cada `--cada` segundos de cada partida real):

  alcance      el ítem recomendado, ¿se puede pagar con el bolsillo de ese momento?
  tiempo       coste medio recomendado frente al coste medio de las compras reales de
               ese mismo tramo de partida (calibración por minuto)
  cobertura    % de compras reales que el coach tuvo como objetivo ±1 minuto
  vaivén       cambios de objetivo que no son una compra (ver linea_tiempo.py)
  sesgo        cuota de cada ítem en las recomendaciones frente a su cuota en las
               compras reales: los que salen mucho más (sobreusados) y mucho menos
               (infrautilizados) que en el meta observado
  seguridad    recomendaciones por encima de lo que hay en el bolsillo, 800 después del
               minuto 10, y muestras sin objetivo

No inventa datos: las compras reales y el net worth salen de `data/replay_cache.json`
(626 partidas). Las almas de los enemigos no están en ese archivo y se simulan, como en
`linea_tiempo.py`; la salida lo dice.

Uso:
    python3 herramientas/banco_partidas.py                       # todas, cada 30 s
    python3 herramientas/banco_partidas.py --partidas 120 --cada 20
    python3 herramientas/banco_partidas.py --enemigos atras --salida salida/banco/atras.json
"""
import argparse
import importlib.util
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from multiprocessing import Pool

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.motor_api import Motor  # noqa: E402

CACHE = os.path.join(RAIZ, "data", "replay_cache.json")
# Nombrado por TU situación: «atras» = los rivales van por encima.
FACTOR = {"atras": 1.22, "parejo": 1.0, "arriba": 0.82}


def _lt():
    ruta = os.path.join(RAIZ, "herramientas", "linea_tiempo.py")
    spec = importlib.util.spec_from_file_location("linea_tiempo", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LT = _lt()


def _indice_heroes():
    with open(os.path.join(RAIZ, "data", "heroes.json"), encoding="utf-8") as f:
        return {k: v["nombre"].lower().replace(" ", "_") for k, v in json.load(f).items()}


def muestrear(tarea):
    """Muestrea una partida entera. Corre en un proceso aparte."""
    indice_partida, cada, enemigos = tarea
    motor = Motor()
    indice = _indice_heroes()
    partida = indice_partida
    muestras = []
    t = 0
    fin = partida.get("duracion_s") or 0
    while t <= fin:
        e = LT.estado_simulado(partida, t, indice, enemigos)
        r = motor.analizar_dict(e)
        d = r.get("decision") or {}
        item = d.get("item") or {}
        bolsillo = d.get("bolsillo")
        muestras.append({
            "t": t,
            "almas": e["yo"]["almas"],
            "bolsillo": bolsillo,
            "item": item.get("id"),
            "nombre": item.get("nombre"),
            "costo": item.get("costo"),
            "costo_lista": item.get("costo_lista") or item.get("costo"),
            "target": d.get("target"),
            "target_nombre": d.get("target_nombre"),
            "accion": d.get("accion"),
            "modo": d.get("modo"),
            "faltan": d.get("faltan"),
            "perfil": (r.get("perfil") or {}).get("etiqueta"),
            "items": list(e["yo"]["items"]),
        })
        t += cada
    compras = [{"t": i["t"], "id": i["id"]} for i in partida["yo"]["items"]
               if i["id"] in motor.conoc["items"]]
    return {
        "match_id": partida["match_id"],
        "dur": fin,
        "gane": partida.get("gane"),
        "muestras": muestras,
        "compras": compras,
    }


def tramo(t):
    if t < 600:
        return "0-10"
    if t < 1200:
        return "10-20"
    if t < 1800:
        return "20-30"
    return "30+"


def agregar(resultados, cada):
    """Cuentas globales, calibración por tramo, sesgo y avisos de seguridad."""
    reco = Counter()            # id -> veces como objetivo/recomendación
    reco_tramo = defaultdict(Counter)
    real = Counter()            # id -> compras reales
    real_tramo = defaultdict(Counter)
    minutos_reco = defaultdict(list)
    minutos_real = defaultdict(list)
    coste_reco = defaultdict(list)
    coste_real = defaultdict(list)
    perfiles = Counter()

    total = 0
    pagable = 0
    caro = 0
    milexp = 0          # 800 después del minuto 10
    sin_objetivo = 0
    completos = 0
    refuerzos = 0
    caros_pronto = 0
    solo_tiempo = 0
    inventario_igual = 0
    cambios_opinion = 0
    por_partida = []

    for r in resultados:
        ms = r["muestras"]
        for m in ms:
            total += 1
            perfiles[m["perfil"]] += 1
            if m["item"] is None:
                sin_objetivo += 1
            if m["modo"] == "completo":
                completos += 1
            if ((m["costo_lista"] or 0) <= 800 and m["t"] >= 600
                    and m["modo"] != "componente"):
                milexp += 1
            if m["modo"] == "refuerzo":
                refuerzos += 1
            if (m["costo_lista"] or 0) >= 6400 and m["t"] < 960:
                caros_pronto += 1
            if m["bolsillo"] is not None and m["costo"] is not None:
                if m["costo"] <= m["bolsillo"]:
                    pagable += 1
                elif m["accion"] != "AHORRAR":
                    caro += 1
            objetivo = m["target"] or m["item"]
            if objetivo:
                reco[objetivo] += 1
                reco_tramo[tramo(m["t"])][objetivo] += 1
                minutos_reco[objetivo].append(m["t"] / 60.0)
                coste_reco[tramo(m["t"])].append(m["costo"] or 0)
        for a, b in zip(ms, ms[1:]):
            if a["items"] == b["items"]:
                inventario_igual += 1
                o1, o2 = a["target"] or a["item"], b["target"] or b["item"]
                if o1 != o2:
                    solo_tiempo += 1
        opinion = 0
        for a, b in zip(ms, ms[1:]):
            objetivo = b["target"] or b["item"]
            previo = a["target"] or a["item"]
            if objetivo and previo and objetivo != previo:
                if previo not in (b["items"] or []):
                    opinion += 1
        cambios_opinion += opinion
        por_partida.append({"match_id": r["match_id"], "opinion": opinion,
                            "sin_objetivo": sum(1 for x in ms if x["item"] is None),
                            "min": round((r["dur"] or 0) / 60)})
        for c in r["compras"]:
            real[c["id"]] += 1
            real_tramo[tramo(c["t"])][c["id"]] += 1
            minutos_real[c["id"]].append(c["t"] / 60.0)
            coste_real[tramo(c["t"])].append((r.get("_coste") or {}).get(c["id"]) or 0)

    cobertura, ventana = _cobertura(resultados)

    total_reco = sum(reco.values()) or 1
    total_real = sum(real.values()) or 1
    sesgo = []
    for iid in set(reco) | set(real):
        cuota_r = reco[iid] / total_reco
        cuota_m = real[iid] / total_real
        if real[iid] >= 10 or reco[iid] >= 10:
            sesgo.append((round(cuota_r - cuota_m, 4), cuota_r, cuota_m, iid))
    sesgo.sort()

    return {
        "partidas": len(resultados),
        "muestras": total,
        "pagable_pct": round(100 * pagable / total, 1) if total else 0,
        "caro_sin_ahorrar": caro,
        "ochocientos_tarde": milexp,
        "sin_objetivo": sin_objetivo,
        "completos": completos,
        "refuerzos": refuerzos,
        "caros_pronto": caros_pronto,
        "flips_solo_tiempo": solo_tiempo,
        "pct_flips_solo_tiempo": round(100 * solo_tiempo / max(1, inventario_igual), 2),
        "cambios_opinion": cambios_opinion,
        "cambios_por_partida": round(cambios_opinion / max(1, len(resultados)), 2),
        "cobertura_pct": cobertura,
        "ventana_min": ventana,
        "perfiles": dict(perfiles),
        "reco": dict(reco),
        "real": dict(real),
        "reco_tramo": {k: dict(v) for k, v in reco_tramo.items()},
        "real_tramo": {k: dict(v) for k, v in real_tramo.items()},
        "minutos_reco": {k: round(statistics.fmean(v), 1) for k, v in minutos_reco.items()},
        "minutos_real": {k: round(statistics.fmean(v), 1) for k, v in minutos_real.items()},
        "coste_reco": {k: round(statistics.fmean(v)) for k, v in coste_reco.items() if v},
        "coste_real": {k: round(statistics.fmean(v)) for k, v in coste_real.items() if v},
        "sesgo": sesgo,
        "peores_vaivenes": sorted(por_partida, key=lambda x: -x["opinion"])[:10],
        "cada_s": cada,
    }


def _cobertura(resultados):
    """% de compras reales que el coach tuvo como objetivo ±`ventana` segundos."""
    ventana = 60
    aciertos = total = 0
    for r in resultados:
        objetivo_por_t = {m["t"]: (m["target"] or m["item"]) for m in r["muestras"]}
        tiempos = sorted(objetivo_por_t)
        if not tiempos:
            continue
        for c in r["compras"]:
            if c["t"] < 120:      # la apertura la compra el jugador solo, es trampa
                continue
            total += 1
            cerca = [objetivo_por_t[t] for t in tiempos if abs(t - c["t"]) <= ventana]
            if c["id"] in cerca:
                aciertos += 1
    return (round(100 * aciertos / total, 1) if total else 0), ventana // 60


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--partidas", type=int, default=0, help="0 = todas")
    ap.add_argument("--cada", type=int, default=30)
    ap.add_argument("--enemigos", choices=sorted(FACTOR), default="parejo")
    ap.add_argument("--paralelo", type=int, default=0, help="0 = núcleos - 2")
    ap.add_argument("--salida", default=None)
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()

    with open(CACHE, encoding="utf-8") as f:
        datos = json.load(f)
    if a.partidas:
        datos = datos[:a.partidas]
    motor = Motor()
    nombres = {iid: d.get("nombre", iid) for iid, d in motor.conoc["items"].items()}
    costes = {iid: d.get("costo") or 0 for iid, d in motor.conoc["items"].items()}

    tareas = [(p, a.cada, a.enemigos) for p in datos]
    procesos = a.paralelo or max(1, (os.cpu_count() or 2) - 2)
    t0 = time.perf_counter()
    with Pool(procesos) as pool:
        resultados = pool.map(muestrear, tareas, chunksize=4)
    seg = time.perf_counter() - t0
    for r in resultados:                       # coste de las compras reales
        r["_coste"] = costes

    res = agregar(resultados, a.cada)
    res["segundos"] = round(seg, 1)
    res["procesos"] = procesos
    res["enemigos"] = "simulados (" + a.enemigos + ")"

    def nom(iid):
        return nombres.get(iid, iid)

    print(f"== banco de partidas · {res['partidas']} partidas · cada {a.cada} s · "
          f"{res['muestras']} muestras · {seg:.0f} s con {procesos} procesos ==")
    print(f"alcanzable ................ {res['pagable_pct']}% de las muestras")
    print(f"recomendadas caras sin AHORRAR . {res['caro_sin_ahorrar']}")
    print(f"800 después del minuto 10 .. {res['ochocientos_tarde']}")
    print(f"muestras sin objetivo ...... {res['sin_objetivo']}")
    print(f"«build completo» ........... {res['completos']}")
    print(f"modo refuerzo .............. {res['refuerzos']} muestras")
    print(f"6400 antes del minuto 16 ... {res['caros_pronto']}")
    print(f"cambios SOLO por el reloj .. {res['pct_flips_solo_tiempo']}% de las muestras "
          f"con el mismo inventario")
    print(f"cambios de opinión ......... {res['cambios_por_partida']} por partida")
    print(f"cobertura (±{res['ventana_min']} min) ....... {res['cobertura_pct']}% de las "
          f"compras reales")
    print(f"perfiles ................... {res['perfiles']}")
    print("\ncalibración por tramo (coste medio recomendado vs real):")
    for k in ("0-10", "10-20", "20-30", "30+"):
        print(f"  {k:6}  reco {res['coste_reco'].get(k, 0):6,}   "
              f"real {res['coste_real'].get(k, 0):6,}")

    print(f"\nítems que el coach usa MENOS que el meta (cuota reco − cuota real):")
    for d, cr, cm, iid in res["sesgo"][:a.top]:
        print(f"  {nom(iid)[:26]:26} {d:+.1%}  reco {cr:.1%} vs real {cm:.1%}")
    print(f"\nítems que el coach usa MÁS que el meta:")
    for d, cr, cm, iid in list(reversed(res["sesgo"]))[:a.top]:
        print(f"  {nom(iid)[:26]:26} {d:+.1%}  reco {cr:.1%} vs real {cm:.1%}")

    print("\npeores vaivenes:", res["peores_vaivenes"][:5])

    ruta = a.salida or os.path.join(RAIZ, "salida", "banco",
                                    f"banco-{a.enemigos}-{a.cada}s.json")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f"\nJSON: {os.path.relpath(ruta, RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

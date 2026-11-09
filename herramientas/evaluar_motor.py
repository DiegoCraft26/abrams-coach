#!/usr/bin/env python3
"""Evalúa el motor sobre partidas reales y compara configuraciones (A/B).

No necesita el juego, ni la pantalla, ni red: usa `data/replay_cache.json`, que trae 626
partidas de Abrams con la línea de tiempo de compras y net worth. Para cada compra real
reconstruye el estado de ese segundo y mide:

  residual    lift residual medio del ítem recomendado (lo que el proyecto considera
              "rinde por encima de lo esperado para su minuto")
  alcanzable  % de recomendaciones que el jugador podía pagar en ese momento
  diversidad  cuántos ítems distintos salen como primera recomendación
  estable     % de estados consecutivos que no cambian de primera recomendación
  acierto     % de veces que el ítem recomendado es el que el jugador compró (métrica de
              popularidad: sirve de control, no de objetivo)
  latencia    ms por consulta

Uso:
    python3 herramientas/evaluar_motor.py --partidas 120
    python3 herramientas/evaluar_motor.py --partidas 120 --config '{"w_cadena": 0.6}' --etiqueta antes
"""
import argparse
import json
import os
import statistics
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.motor_api import Motor  # noqa: E402

CACHE = os.path.join(RAIZ, "data", "replay_cache.json")


def cargar_cache(limite, ruta=CACHE):
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)
    return datos[:limite] if limite else datos


def almas_en(stats, t):
    """Interpola el net worth en el segundo t."""
    if not stats:
        return None
    if t <= stats[0]["t"]:
        return stats[0]["neto"]
    for a, b in zip(stats, stats[1:]):
        if a["t"] <= t <= b["t"]:
            if b["t"] == a["t"]:
                return b["neto"]
            f = (t - a["t"]) / (b["t"] - a["t"])
            return int(a["neto"] + f * (b["neto"] - a["neto"]))
    return stats[-1]["neto"]


def estado_en(partida, t, heroes_por_id):
    yo = partida["yo"]
    propios = [i["id"] for i in yo["items"]
               if i["t"] < t and (not i["vendido"] or i["vendido"] > t)]
    enemigos, aliados = [], []
    for j in partida["jugadores"]:
        if j["slot"] == yo["slot"]:
            continue
        nombre = heroes_por_id.get(str(j["hero"]), str(j["hero"]))
        (enemigos if j["team"] != yo["team"] else aliados).append({"heroe": nombre})
    return {"t": t, "yo": {"heroe": "Abrams", "almas": almas_en(yo["stats"], t),
                           "items": propios},
            "enemigos": enemigos, "aliados": aliados, "confianza": 1.0, "fuente": "replay"}


def evaluar(motor, partidas, heroes_por_id, desde_min=10, max_estados=4000):
    filas = []
    for partida in partidas:
        compras = [i for i in partida["yo"]["items"]
                   if i["t"] >= desde_min * 60 and i["id"] in motor.conoc["items"]]
        for compra in compras:
            if len(filas) >= max_estados:
                break
            estado = estado_en(partida, compra["t"], heroes_por_id)
            if not estado["yo"]["almas"] or not estado["enemigos"]:
                continue
            t0 = time.perf_counter()
            r = motor.analizar_dict(estado)
            ms = (time.perf_counter() - t0) * 1000
            recos = r.get("recomendaciones") or []
            if not recos:
                continue
            top = recos[0]
            filas.append({
                "match": partida["match_id"],
                "t": compra["t"],
                "top1": top["id"],
                "top1_nombre": top["nombre"],
                "residual": top.get("residual"),
                "costo": top.get("costo"),
                "almas": estado["yo"]["almas"],
                "alcanzable": (top.get("costo") or 0) <= (estado["yo"]["almas"] or 0),
                "acierto": top["id"] == compra["id"],
                "en_top3": compra["id"] in [x["id"] for x in recos],
                "razones": len(top.get("razones") or []),
                "ms": ms,
            })
    return filas


def resumir(filas):
    if not filas:
        return {}
    tops = [f["top1"] for f in filas]
    distintos = len(set(tops))
    estables = sum(1 for a, b in zip(tops, tops[1:]) if a == b)
    por_orden = {}
    for f in filas:
        por_orden.setdefault(f["match"], []).append(f["top1"])
    estabilidad = (sum(sum(1 for a, b in zip(v, v[1:]) if a == b)
                       for v in por_orden.values()) /
                   max(1, sum(len(v) - 1 for v in por_orden.values())))
    return {
        "estados": len(filas),
        "residual_medio": round(statistics.fmean(
            [f["residual"] for f in filas if f["residual"] is not None]), 4),
        "alcanzable_pct": round(100 * sum(f["alcanzable"] for f in filas) / len(filas), 1),
        "diversidad": distintos,
        "top5": sorted(((t, tops.count(t)) for t in set(tops)),
                       key=lambda x: -x[1])[:5],
        "estabilidad_pct": round(100 * estabilidad, 1),
        "acierto_pct": round(100 * sum(f["acierto"] for f in filas) / len(filas), 1),
        "en_top3_pct": round(100 * sum(f["en_top3"] for f in filas) / len(filas), 1),
        "razones_por_reco": round(statistics.fmean([f["razones"] for f in filas]), 2),
        "ms_medio": round(statistics.fmean([f["ms"] for f in filas]), 2),
        "ms_max": round(max(f["ms"] for f in filas), 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--partidas", type=int, default=120)
    ap.add_argument("--desde-min", type=int, default=10)
    ap.add_argument("--max-estados", type=int, default=4000)
    ap.add_argument("--config", default=None, help="overrides JSON del motor")
    ap.add_argument("--etiqueta", default="actual")
    ap.add_argument("--cache", default=CACHE,
                    help="JSON con partidas (por defecto data/replay_cache.json); "
                         "en CI se usa data/replay_muestra.json")
    ap.add_argument("--salida", default=None)
    a = ap.parse_args()

    cfg = json.loads(a.config) if a.config else None
    motor = Motor(cfg=cfg)
    heroes_por_id = {k: v["nombre"].lower().replace(" ", "_")
                     for k, v in json.load(open(os.path.join(RAIZ, "data", "heroes.json"))).items()}
    partidas = cargar_cache(a.partidas, a.cache)
    filas = evaluar(motor, partidas, heroes_por_id, a.desde_min, a.max_estados)
    resumen = resumir(filas)

    print(f"== {a.etiqueta} ==")
    print(f"partidas {len(partidas)} · estados {resumen['estados']}")
    print(f"residual medio top1 ....... {resumen['residual_medio']:+.4f} pp")
    print(f"alcanzable ................ {resumen['alcanzable_pct']}%")
    print(f"diversidad (top1 únicos) .. {resumen['diversidad']}")
    print(f"estabilidad ............... {resumen['estabilidad_pct']}%")
    print(f"acierto vs compra real .... {resumen['acierto_pct']}% (control, no objetivo)")
    print(f"en top3 ................... {resumen['en_top3_pct']}%")
    print(f"razones por recomendación . {resumen['razones_por_reco']}")
    print(f"latencia .................. {resumen['ms_medio']} ms medio / {resumen['ms_max']} ms máx")
    print("top5:", resumen["top5"])

    ruta = a.salida or os.path.join(RAIZ, "salida", "evaluaciones",
                                    f"evaluacion-{a.etiqueta}.json")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"etiqueta": a.etiqueta, "config": cfg, "resumen": resumen,
                   "muestras": filas[:2000]}, f, ensure_ascii=False, indent=1)
    print("guardado:", ruta)
    return 0


if __name__ == "__main__":
    sys.exit(main())

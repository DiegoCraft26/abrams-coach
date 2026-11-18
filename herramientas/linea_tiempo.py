#!/usr/bin/env python3
"""Línea de tiempo: rejuega una partida real y enseña qué recomienda el coach segundo a
segundo. Es el visor que faltaba para responder «¿por qué cambia de opinión?» sin abrir el
juego.

Los datos salen de `data/replay_cache.json`: 626 partidas de Abrams con la hora exacta de
cada compra y el net worth a lo largo de la partida. Ese archivo **no trae las almas de los
enemigos**, así que la economía rival se simula y se dice en la salida (`--enemigos`).
Lo que sí es real: tu inventario en cada segundo, tus almas, tu reloj y los héroes de los
dos equipos.

Uso:
    python3 herramientas/linea_tiempo.py --lista
    python3 herramientas/linea_tiempo.py --match 132662221 --cada 30
    python3 herramientas/linea_tiempo.py --match 132662221 --cada 60 --enemigos atras
    python3 herramientas/linea_tiempo.py --resumen 40
"""
import argparse
import importlib.util
import json
import os
import statistics
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.motor_api import Motor  # noqa: E402

CACHE = os.path.join(RAIZ, "data", "replay_cache.json")


def _herramientas():
    """Reutiliza los helpers del evaluador (una sola definición de «estado en t»)."""
    ruta = os.path.join(RAIZ, "herramientas", "evaluar_motor.py")
    spec = importlib.util.spec_from_file_location("evaluar_motor", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


EV = _herramientas()


def heroes_por_id():
    with open(os.path.join(RAIZ, "data", "heroes.json"), encoding="utf-8") as f:
        return {k: v["nombre"].lower().replace(" ", "_") for k, v in json.load(f).items()}


def partidas(limite=None):
    with open(CACHE, encoding="utf-8") as f:
        datos = json.load(f)
    return datos[:limite] if limite else datos


# Nombrado por TU situación: «atras» = los rivales van por encima.
FACTOR = {"atras": 1.22, "parejo": 1.0, "arriba": 0.82}


def estado_simulado(partida, t, indice, enemigos="parejo", sin_economia=False):
    """Estado en t con la economía rival explicitada como simulación."""
    e = EV.estado_en(partida, t, indice)
    if sin_economia:
        e["enemigos"] = [{"heroe": x["heroe"]} for x in e["enemigos"]]
        e["aliados"] = []
        return e
    mío = e["yo"]["almas"] or 0
    factor = FACTOR.get(enemigos, 1.0)
    e["aliados"] = [{"heroe": x["heroe"], "almas": int(mío * 0.95)}
                    for x in e.get("aliados") or []]
    e["enemigos"] = [{"heroe": x["heroe"], "almas": int(mío * factor)}
                     for x in e.get("enemigos") or []]
    return e


def recorrer(motor, partida, indice, cada=30, enemigos="parejo", sin_economia=False,
             desde=0, hasta=None):
    """Lista de muestras (t, decisión, perfil, camino) en pasos de `cada` segundos."""
    hasta = hasta if hasta is not None else partida.get("duracion_s") or 0
    muestras = []
    t = max(0, desde)
    while t <= hasta:
        e = estado_simulado(partida, t, indice, enemigos, sin_economia)
        r = motor.analizar_dict(e)
        d = r.get("decision") or {}
        item = d.get("item") or {}
        muestras.append({
            "t": t,
            "almas": e["yo"]["almas"],
            "accion": d.get("accion"),
            "modo": d.get("modo"),
            "item": item.get("id"),
            "nombre": item.get("nombre"),
            "target": d.get("target"),
            "target_nombre": d.get("target_nombre"),
            "costo": item.get("costo"),
            "motivo": (d.get("motivo") or "").split(" · ")[0],
            "perfil": (r.get("perfil") or {}).get("etiqueta"),
            "alerta": (r.get("amenazas") or {}).get("alerta"),
            "camino": [x.get("nombre") for x in (r.get("camino") or [])[:3]],
            "items": list(e["yo"]["items"]),
        })
        t += cada
    return muestras


def resumir_muestras(muestras, cada=30, campo="target"):
    """Cambios de opinión, rachas, «build completo» y repeticiones.

    Se mide sobre `target` (la dirección del build) y no sobre el ítem a comprar: cuando
    el motor recomienda el componente de lo mismo, no es un cambio de opinión.
    """
    cambios, rachas, actual, inicio = [], [], None, None
    completos = 0
    cuenta = {}
    for m in muestras:
        if m["modo"] == "completo":
            completos += 1
        if m[campo]:
            cuenta[m.get(campo + "_nombre") or m["nombre"]] = \
                cuenta.get(m.get(campo + "_nombre") or m["nombre"], 0) + 1
        if m[campo] != actual:
            if actual is not None:
                cambios.append(m["t"])
                rachas.append(m["t"] - inicio)
            actual, inicio = m[campo], m["t"]
    if actual is not None and inicio is not None and muestras:
        rachas.append(muestras[-1]["t"] - inicio)
    # Cambio de opinión de verdad: cambia el objetivo y el anterior NO se compró. Si se
    # compró, es progreso normal del build y no cuenta.
    opinion = 0
    for prev, cur in zip(muestras, muestras[1:]):
        if cur[campo] and prev[campo] and cur[campo] != prev[campo]:
            if prev[campo] not in (cur.get("items") or []):
                opinion += 1
    return {
        "cambios_opinion": opinion,
        "opinion_por_10min": round(opinion / max(1, len(muestras) * cada / 600), 2),
        "muestras": len(muestras),
        "cambios": len(cambios),
        "cambios_por_10min": round(len(cambios) / max(1, len(muestras) * cada / 600), 2),
        "racha_mediana_s": int(statistics.median(rachas)) if rachas else 0,
        "racha_max_s": max(rachas) if rachas else 0,
        "completos": completos,
        "repetido": sorted(cuenta.items(), key=lambda kv: -kv[1])[:5],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lista", action="store_true", help="lista partidas disponibles")
    ap.add_argument("--match", type=int, default=None)
    ap.add_argument("--cada", type=int, default=30, help="segundos entre muestras")
    ap.add_argument("--desde", type=int, default=0)
    ap.add_argument("--hasta", type=int, default=None)
    ap.add_argument("--enemigos", choices=sorted(FACTOR), default="parejo")
    ap.add_argument("--sin-economia", action="store_true",
                    help="sin almas de rivales: solo camino y compra")
    ap.add_argument("--resumen", type=int, default=0,
                    help="agrega N partidas y no imprime el detalle")
    ap.add_argument("--partida", type=int, default=0,
                    help="índice de partida para --resumen (0 = todas las N)")
    a = ap.parse_args()

    datos = partidas()
    indice = heroes_por_id()

    if a.lista:
        for i, p in enumerate(datos[:60]):
            dur = (p.get("duracion_s") or 0) // 60
            print(f"{i:3}  {p['match_id']}  {dur:2} min  "
                  f"{'ganada' if p.get('gane') else 'perdida'}")
        print(f"... {len(datos)} partidas en {os.path.relpath(CACHE, RAIZ)}")
        return 0

    motor = Motor()

    if a.resumen:
        seleccion = datos[:a.resumen]
        filas = []
        for p in seleccion:
            m = recorrer(motor, p, indice, a.cada, a.enemigos, a.sin_economia)
            if not m:
                continue
            filas.append((p, resumir_muestras(m, a.cada),
                          resumir_muestras(m, a.cada, campo="item")))
        if not filas:
            print("sin muestras")
            return 1
        print(f"== {len(filas)} partidas · cada {a.cada} s · enemigos "
              f"{'simulados (' + a.enemigos + ')' if not a.sin_economia else 'sin economía'} ==")
        campos = ("cambios", "cambios_por_10min", "cambios_opinion",
                  "opinion_por_10min", "racha_mediana_s", "racha_max_s", "completos")
        for etiqueta, indice in (("objetivo", 1), ("compra", 2)):
            print(f"-- {etiqueta} --")
            for k in campos:
                vals = [f[indice][k] for f in filas]
                print(f"{k:20} media {statistics.fmean(vals):8.2f}   "
                      f"mediana {statistics.median(vals):8.2f}   máx {max(vals):6.0f}")
        total = {}
        for _, r, _ in filas:
            for nombre, n in r["repetido"]:
                total[nombre] = total.get(nombre, 0) + n
        print("ítems más repetidos:", sorted(total.items(), key=lambda kv: -kv[1])[:8])
        return 0

    if a.match is None:
        p = datos[a.partida]
    else:
        p = next((x for x in datos if x["match_id"] == a.match), None)
    if p is None:
        print(f"no está {a.match} en el cache; usa --lista")
        return 1

    m = recorrer(motor, p, indice, a.cada, a.enemigos, a.sin_economia,
                 a.desde, a.hasta)
    print(f"partida {p['match_id']} · {p.get('duracion_s', 0)//60} min · "
          f"{'ganada' if p.get('gane') else 'perdida'} · "
          f"enemigos {'simulados (' + a.enemigos + ')' if not a.sin_economia else 'sin economía'}")
    anterior = None
    for x in m:
        marca = "  " if x["target"] == anterior else "->"
        nombre = (x["nombre"] or "—")[:26]
        objetivo = (x["target_nombre"] or "")[:24]
        print(f"{marca} {x['t']//60:2}:{x['t']%60:02}  {x['almas'] or 0:6}  "
              f"{(x['accion'] or '—'):8} {nombre:24} -> {objetivo:24} "
              f"{(x['perfil'] or '—'):14} {x['motivo'][:46]}")
        anterior = x["target"]
    r = resumir_muestras(m, a.cada)
    print(f"\ncambios {r['cambios']} · cada {r['cambios_por_10min']} por 10 min · "
          f"racha mediana {r['racha_mediana_s']} s · máx {r['racha_max_s']} s · "
          f"«completo» {r['completos']} veces")
    print("repetido:", r["repetido"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Analiza la progresión de rango y compara escaladores rápidos contra la mediana.

Unidad de rango: `ranked_display_badge` (badge = rango*10 + subrango, ver
`/v1/assets/ranks`). Una división = 6 subrangos = 1 rango completo (p. ej. Archon → Oracle).

Ventana de estudio: temporada 2 desde 1793908800 (2026-11-05 20:00 UTC). Es la única
temporada con ~13 días de datos al momento del corte, así que "rápido" se mide dentro de
ella; los logros de temporadas anteriores no sirven porque el rango se reinicia.

Criterio primario de **escalador rápido** (explícito, elegido para no confundir volumen
con velocidad):
    población = cuentas con ≥30 partidas rankeadas en la temporada 2
    rápido    = ganancia neta ≥6 subrangos (≥1 división completa) en la temporada
El piso de 30 partidas se aplica a **ambos grupos**, así que la comparación de volumen
(partidas/día) no está contaminada por el filtro. Se reporta la sensibilidad del criterio
con umbrales 4, 6, 8, 10 y el criterio literal del dueño (≥3 divisiones en ≤14 días con
≥40 partidas), que se evalúa aparte.

Salida: datos/macro/analisis.json y datos/macro/tablas.md. Sin red.

Uso:
    python3 herramientas/macro/analizar.py
    python3 herramientas/macro/analizar.py --subrangos 8 --minimo-rankeds 40
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import os
import sys
from collections import Counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (escribir_json, fisher_exact, leer_json,  # noqa: E402
                    mann_whitney, mediana)

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATOS = os.path.join(RAIZ, "datos", "macro")
CACHE_HIST = os.path.join(DATOS, "cache", "historial")
CACHE_MATES = os.path.join(DATOS, "cache", "mates")
REGIONES = os.path.join(DATOS, "cache", "regiones.json")
SALIDA_JSON = os.path.join(DATOS, "analisis.json")
SALIDA_MD = os.path.join(DATOS, "tablas.md")

TEMPORADA_2 = 1793908800          # /v1/assets/ranked-seasons · 2026-11-05 20:00 UTC
HUECO_SESION_S = 2 * 3600
SUB_POR_DIVISION = 6

REGION_TZ = {
    "us_east": "America/New_York", "us_southeast": "America/New_York",
    "us_northeast": "America/New_York", "us_north_central": "America/Chicago",
    "us_south_central": "America/Chicago", "us_central": "America/Chicago",
    "us_southwest": "America/Los_Angeles", "us_west": "America/Los_Angeles",
    "us_northwest": "America/Los_Angeles", "london": "Europe/London",
    "spain": "Europe/Madrid", "eu_west": "Europe/Berlin", "eu_east": "Europe/Berlin",
    "eu_north": "Europe/Stockholm", "frankfurt": "Europe/Berlin",
    "dpkt-frankfurt": "Europe/Berlin", "dpkt-stockholm": "Europe/Stockholm",
    "dpkt-london": "Europe/London", "helsinki": "Europe/Helsinki",
    "poland": "Europe/Warsaw", "russia": "Europe/Moscow",
    "south_america": "America/Sao_Paulo", "brazil": "America/Sao_Paulo",
    "argentina": "America/Argentina/Buenos_Aires", "chile": "America/Santiago",
    "peru": "America/Lima", "mexico": "America/Mexico_City",
    "australia": "Australia/Sydney", "hong_kong": "Asia/Hong_Kong",
    "singapore": "Asia/Singapore", "japan": "Asia/Tokyo", "korea": "Asia/Seoul",
    "asia": "Asia/Singapore", "dubai": "Asia/Dubai",
    "falkenstein": "Europe/Berlin", "dpkt-vienna": "Europe/Vienna",
    "dpkt-fujairah": "Asia/Dubai", "dpkt-amsterdam": "Europe/Amsterdam",
}


def unidades(badge):
    return (badge // 10) * SUB_POR_DIVISION + (badge % 10)


def cargar():
    semilla = leer_json(os.path.join(DATOS, "semilla.json"), {}) or {}
    regs = leer_json(REGIONES, {}) or {}
    cuentas = {}
    for ruta in sorted(glob.glob(os.path.join(CACHE_HIST, "*.json"))):
        acc = int(os.path.basename(ruta)[:-5])
        datos = leer_json(ruta)
        if isinstance(datos, list):
            cuentas[acc] = datos
    return semilla, regs, cuentas


def tz_de(acc, regs):
    reg = (regs.get(str(acc)) or {}).get("region")
    if not reg:
        return None, None
    nombre = REGION_TZ.get(reg)
    if not nombre:
        return None, reg
    try:
        return ZoneInfo(nombre), reg
    except ZoneInfoNotFoundError:
        return None, reg


def mejor_ventana(tiempos, insignias, minimo_n, max_dias=14.0):
    """Mayor salto de badge en una ventana de ≤max_dias con al menos `minimo_n` partidas."""
    mejor = {"div": None, "sub": None, "n": 0, "dias": 0.0}
    for i in range(len(tiempos)):
        for j in range(i, len(tiempos)):
            dias = (tiempos[j] - tiempos[i]) / 86400.0
            if dias > max_dias:
                break
            n = j - i + 1
            if n < minimo_n:
                continue
            div = insignias[j] // 10 - insignias[i] // 10
            sub = unidades(insignias[j]) - unidades(insignias[i])
            if mejor["sub"] is None or (sub, div, n) > (mejor["sub"], mejor["div"], mejor["n"]):
                mejor = {"div": div, "sub": sub, "n": n, "dias": round(dias, 2)}
    return mejor


def caracterizar(acc, filas, tz, region):
    filas = sorted(filas, key=lambda x: (x.get("start_time") or 0, x.get("match_id") or 0))
    s2 = [f for f in filas if (f.get("start_time") or 0) >= TEMPORADA_2]
    # actividad rankeada: badge conocido o delta conocido
    rk = [f for f in s2 if (f.get("ranked_display_badge") or 0) > 0
          or f.get("ranked_delta") is not None]
    serie = [f for f in s2 if (f.get("ranked_display_badge") or 0) > 0]
    f_out = {
        "account_id": acc, "region": region,
        "tz": str(tz) if tz else None,
        "n_historial": len(filas), "n_s2": len(s2),
        "n_ranked_s2": len(rk), "n_serie_badge": len(serie),
    }
    if len(serie) < 2:
        f_out["sin_serie"] = True
        return f_out

    insignias = [int(f["ranked_display_badge"]) for f in serie]
    tiempos = [int(f.get("start_time") or 0) for f in serie]
    f_out.update({
        "badge_inicio": insignias[0],
        "badge_fin": insignias[-1],
        "badge_max": max(insignias),
        "div_neto": insignias[-1] // 10 - insignias[0] // 10,
        "sub_neto": unidades(insignias[-1]) - unidades(insignias[0]),
        "sub_max": unidades(max(insignias)) - unidades(insignias[0]),
    })
    f_out["sub_por_100"] = round(100.0 * f_out["sub_neto"] / len(serie), 1)
    f_out["pct_mejora"] = round(100.0 * f_out["sub_neto"] / len(serie), 1)

    f_out["ventana_40"] = mejor_ventana(tiempos, insignias, 40)
    f_out["ventana_20"] = mejor_ventana(tiempos, insignias, 20)

    deltas = [int(f["ranked_delta"]) for f in rk if f.get("ranked_delta") is not None]
    f_out["delta_acumulado"] = sum(deltas)
    f_out["delta_medio"] = round(sum(deltas) / len(deltas), 1) if deltas else None

    resultados = [f.get("player_match_outcome") for f in rk]
    jugables = [o for o in resultados if o in (1, 2)]
    f_out["wr_s2"] = round(sum(1 for o in jugables if o == 1) / len(jugables), 3) if jugables else None

    n = len(rk)
    f_out["n_proteccion"] = sum(1 for f in rk if f.get("ranked_used_demotion_protection"))
    f_out["pct_proteccion"] = round(100.0 * f_out["n_proteccion"] / n, 1)
    f_out["n_calibracion"] = sum(1 for f in rk if (f.get("ranked_calibration_match") or 0) > 0)
    f_out["pct_calibracion"] = round(100.0 * f_out["n_calibracion"] / n, 1)
    f_out["n_lowpri"] = sum(1 for f in rk if f.get("low_pri_pool"))
    f_out["pct_lowpri"] = round(100.0 * f_out["n_lowpri"] / n, 1)
    f_out["n_abandono"] = sum(1 for f in rk if (f.get("abandoned_time_s") or 0) > 0)
    f_out["pct_abandono"] = round(100.0 * f_out["n_abandono"] / n, 1)
    f_out["n_penalizado"] = sum(1 for f in rk if f.get("player_match_outcome") in (3, 4))

    dias = sorted({dt.datetime.fromtimestamp(t, dt.timezone.utc).date() for t in tiempos})
    span = max(1, (max(tiempos) - min(tiempos)) // 86400 + 1)
    f_out.update({
        "dias_activos": len(dias), "span_dias": span,
        "partidas_por_dia": round(len(serie) / span, 2),
        "partidas_por_dia_activo": round(len(serie) / len(dias), 2),
        "pct_dias_temporada": round(100.0 * len(dias) / 13.5, 1),
    })

    # sesiones (corte por hueco ≥ 2 h) y ritmo de cola
    sesiones, actual = [], [serie[0]]
    for previo, siguiente in zip(serie, serie[1:]):
        if (siguiente.get("start_time") or 0) - (previo.get("start_time") or 0) >= HUECO_SESION_S:
            sesiones.append(actual)
            actual = [siguiente]
        else:
            actual.append(siguiente)
    sesiones.append(actual)
    largos = [len(s) for s in sesiones]
    duraciones = [((s[-1].get("start_time") or 0) + (s[-1].get("match_duration_s") or 0)
                   - (s[0].get("start_time") or 0)) / 3600.0 for s in sesiones]
    huecos = [((b.get("start_time") or 0) - (a.get("start_time") or 0)
               - (a.get("match_duration_s") or 0)) / 60.0
              for s in sesiones for a, b in zip(s, s[1:])]
    f_out.update({
        "n_sesiones": len(sesiones),
        "sesion_media": round(sum(largos) / len(largos), 2),
        "sesion_max": max(largos),
        "sesion_duracion_media_h": round(sum(duraciones) / len(duraciones), 2),
        "cola_mediana_min": round(mediana([h for h in huecos if h >= 0]), 1) if huecos else None,
        "pct_sesion_8mas": round(100.0 * sum(1 for x in largos if x >= 8) / len(largos), 1),
    })

    # horario local (zona del servidor de la región; aproximación, se declara)
    if tz:
        horas, finde = Counter(), 0
        for f in serie:
            m = dt.datetime.fromtimestamp(int(f["start_time"]), tz)
            horas[m.hour] += 1
            if m.weekday() >= 5:
                finde += 1
        total = sum(horas.values())
        f_out.update({
            "hora_media": round(sum(h * c for h, c in horas.items()) / total, 2),
            "pct_noche_22_04": round(100.0 * sum(c for h, c in horas.items()
                                                 if h >= 22 or h < 4) / total, 1),
            "pct_tarde_18_22": round(100.0 * sum(c for h, c in horas.items()
                                                 if 18 <= h < 22) / total, 1),
            "pct_madrugada_00_06": round(100.0 * sum(c for h, c in horas.items()
                                                     if h < 6) / total, 1),
            "pct_finde": round(100.0 * finde / total, 1),
            "horas_top3": [h for h, _ in horas.most_common(3)],
        })
    else:
        for clave in ("hora_media", "pct_noche_22_04", "pct_tarde_18_22",
                      "pct_madrugada_00_06", "pct_finde", "horas_top3"):
            f_out[clave] = None

    heroes = Counter(f.get("hero_id") for f in serie)
    f_out.update({
        "n_heroes": len(heroes),
        "pct_heroe_principal": round(100.0 * heroes.most_common(1)[0][1] / len(serie), 1),
        "pct_top3_heroes": round(100.0 * sum(c for _, c in heroes.most_common(3)) / len(serie), 1),
        "n_heroes_min2": sum(1 for _, c in heroes.items() if c >= 2),
    })

    # duplas (si se corrió duplas.py)
    mates = leer_json(os.path.join(CACHE_MATES, f"{acc}.json"))
    if isinstance(mates, list):
        total_mate = sum(int(m.get("matches_played") or 0) for m in mates if isinstance(m, dict))
        top = max((int(m.get("matches_played") or 0) for m in mates if isinstance(m, dict)),
                  default=0)
        f_out["pct_con_dupla"] = round(100.0 * total_mate / max(1, len(serie)), 1)
        f_out["pct_dupla_principal"] = round(100.0 * top / max(1, len(serie)), 1)
    return f_out


VARIABLES = [
    ("badge_inicio", "badge de partida (inicio S2)"),
    ("rango_inicio", "rango de partida (división)"),
    ("n_ranked_s2", "partidas rankeadas S2"),
    ("partidas_por_dia", "partidas de rango por día"),
    ("partidas_por_dia_activo", "partidas por día activo"),
    ("dias_activos", "días con partidas"),
    ("pct_dias_temporada", "% de días de la temporada jugados"),
    ("n_sesiones", "sesiones"),
    ("sesion_media", "partidas por sesión"),
    ("sesion_max", "sesión más larga (partidas)"),
    ("sesion_duracion_media_h", "duración media de sesión (h)"),
    ("cola_mediana_min", "minutos entre partidas (cola)"),
    ("pct_sesion_8mas", "% sesiones ≥8 partidas"),
    ("delta_acumulado", "delta de puntos acumulado"),
    ("delta_medio", "delta medio por partida"),
    ("wr_s2", "winrate S2"),
    ("pct_tarde_18_22", "% partidas 18–22 local"),
    ("pct_noche_22_04", "% partidas 22–04 local"),
    ("pct_madrugada_00_06", "% partidas 00–06 local"),
    ("hora_media", "hora local media"),
    ("pct_finde", "% partidas en fin de semana"),
    ("n_heroes", "héroes distintos"),
    ("pct_heroe_principal", "% con el héroe principal"),
    ("pct_top3_heroes", "% con los 3 héroes top"),
    ("pct_abandono", "% abandonos"),
    ("pct_lowpri", "% en low priority"),
    ("pct_calibracion", "% partidas de calibración"),
    ("pct_proteccion", "% con protección de descenso"),
    ("n_proteccion", "partidas con protección"),
    ("pct_con_dupla", "% de partidas con compañero fijo (dupla)"),
    ("pct_dupla_principal", "% con la dupla principal"),
]


def comparar(rapidas, resto):
    filas = []
    for campo, etiqueta in VARIABLES:
        a = [g.get(campo) for g in rapidas]
        b = [g.get(campo) for g in resto]
        if sum(v is not None for v in a) < 8 or sum(v is not None for v in b) < 8:
            continue
        r = mann_whitney(a, b)
        filas.append({"campo": campo, "variable": etiqueta,
                      "mediana_rapido": mediana(a), "mediana_resto": mediana(b),
                      "n_rapido": r["n1"], "n_resto": r["n2"], "U": r["U"],
                      "p": None if r["p"] is None else round(r["p"], 4),
                      "cliff": r["delta"]})
    return filas


def proporciones(rapidas, resto):
    salida = []
    for etiqueta, campo in (("algún abandono", "n_abandono"),
                            ("alguna partida low-pri", "n_lowpri"),
                            ("usó protección de descenso", "n_proteccion"),
                            ("tuvo partidas de calibración", "n_calibracion")):
        a = sum(1 for f in rapidas if (f.get(campo) or 0) > 0)
        c = sum(1 for f in resto if (f.get(campo) or 0) > 0)
        p = fisher_exact(a, len(rapidas) - a, c, len(resto) - c)
        salida.append({"variable": etiqueta, "a_rapido": a, "n_rapido": len(rapidas),
                       "pct_rapido": round(100.0 * a / len(rapidas), 1) if rapidas else None,
                       "a_resto": c, "n_resto": len(resto),
                       "pct_resto": round(100.0 * c / len(resto), 1) if resto else None,
                       "p": None if p is None else round(p, 4)})
    return salida


def main():
    ap = argparse.ArgumentParser(description="Escaladores rápidos vs mediana")
    ap.add_argument("--subrangos", type=int, default=6)
    ap.add_argument("--minimo-rankeds", type=int, default=30)
    args = ap.parse_args()

    semilla, regs, cuentas = cargar()
    sin_zona = Counter()
    filas = []
    for acc, datos in cuentas.items():
        tz, region = tz_de(acc, regs)
        if region and not tz:
            sin_zona[region] += 1
        filas.append(caracterizar(acc, datos, tz, region))

    con_serie = [f for f in filas if not f.get("sin_serie")]
    validas = [f for f in con_serie if f["n_ranked_s2"] >= args.minimo_rankeds]
    rapidas = [f for f in validas if f["sub_neto"] >= args.subrangos]
    resto = [f for f in validas if f["sub_neto"] < args.subrangos]

    sensibilidad = []
    for umbral in (2, 4, 6, 8, 10, 12):
        grupo = [f for f in validas if f["sub_neto"] >= umbral]
        sensibilidad.append({
            "umbral_subrangos": umbral,
            "n_rapidas": len(grupo),
            "mediana_partidas_dia_rapidas": mediana([g["partidas_por_dia"] for g in grupo]),
            "mediana_partidas_dia_resto": mediana(
                [g["partidas_por_dia"] for g in validas if g["sub_neto"] < umbral]),
        })

    literal = [f for f in validas
               if f["ventana_40"]["div"] is not None and f["ventana_40"]["div"] >= 3]
    literal_2div = [f for f in validas
                    if f["ventana_40"]["div"] is not None and f["ventana_40"]["div"] >= 2]
    tres_div_todo = [f for f in con_serie if f["ventana_40"]["div"] is not None
                     and f["ventana_40"]["div"] >= 3]

    horasp = Counter(h for f in rapidas for h in (f.get("horas_top3") or []))
    horasr = Counter(h for f in resto for h in (f.get("horas_top3") or []))

    salida = {
        "generado": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "temporada_2_inicio_utc": dt.datetime.fromtimestamp(
            TEMPORADA_2, dt.timezone.utc).isoformat(timespec="seconds"),
        "fuente": "cache/historial/*.json (/v1/players/{id}/match-history)",
        "muestra": {
            "semilla": semilla.get("n_muestra"),
            "semilla_vista_en_ranked": semilla.get("muestra_vistas_en_ranked"),
            "con_historial": len(cuentas),
            "con_serie_badge": len(con_serie),
            "validas": len(validas),
            "minimo_rankeds": args.minimo_rankeds,
            "con_zona": sum(1 for f in validas if f.get("tz")),
            "regiones_sin_zona": dict(sin_zona),
            "regiones": dict(Counter(f.get("region") for f in validas).most_common()),
        },
        "criterio": {
            "primario": f"población = ≥{args.minimo_rankeds} partidas rankeadas en S2; "
                        f"rápido = ganancia neta ≥{args.subrangos} subrangos "
                        f"(≥{args.subrangos / SUB_POR_DIVISION:.1f} divisiones)",
            "rapidas": len(rapidas), "resto": len(resto),
            "literal_3div_40p": len(literal),
            "literal_2div_40p": len(literal_2div),
            "literal_3div_40p_toda_la_muestra": len(tres_div_todo),
        },
        "sensibilidad": sensibilidad,
        "comparacion": comparar(rapidas, resto),
        "proporciones": proporciones(rapidas, resto),
        "horas_top3": {"rapidas": horasp.most_common(), "resto": horasr.most_common()},
        "cuentas": filas,
    }
    escribir_json(SALIDA_JSON, salida)

    lineas = ["# Tablas generadas · macro-cola", "",
              f"`{salida['generado']}` · temporada 2 desde {salida['temporada_2_inicio_utc']}",
              "", f"**Criterio:** {salida['criterio']['primario']}", "",
              f"- con historial: {len(cuentas)} · con serie de badge: {len(con_serie)} "
              f"· válidas (≥{args.minimo_rankeds} rankeadas): {len(validas)}",
              f"- rápidas: {len(rapidas)} · resto: {len(resto)}",
              f"- literal ≥3 div / 40 partidas: {len(literal)} · "
              f"≥2 div / 40 partidas: {len(literal_2div)}",
              f"- con zona horaria resuelta: {salida['muestra']['con_zona']}", "",
              "## Comparación (Mann-Whitney bilateral, δ de Cliff)", "",
              "| variable | mediana rápidos | mediana resto | n1 | n2 | U | p | δ |",
              "|---|---|---|---|---|---|---|---|"]
    for f in salida["comparacion"]:
        lineas.append(f"| {f['variable']} | {_f(f['mediana_rapido'])} | {_f(f['mediana_resto'])} "
                      f"| {f['n_rapido']} | {f['n_resto']} | {_f(f['U'])} | {_f(f['p'])} "
                      f"| {_f(f['cliff'])} |")
    lineas += ["", "## Proporciones (Fisher bilateral)", "",
               "| variable | rápidos | resto | p |", "|---|---|---|---|"]
    for f in salida["proporciones"]:
        lineas.append(f"| {f['variable']} | {f['a_rapido']}/{f['n_rapido']} "
                      f"({f['pct_rapido']} %) | {f['a_resto']}/{f['n_resto']} "
                      f"({f['pct_resto']} %) | {_f(f['p'])} |")
    lineas += ["", "## Sensibilidad del umbral", "",
               "| umbral subrangos | n rápidas | mediana partidas/día (rápidas) | "
               "mediana partidas/día (resto) |", "|---|---|---|---|"]
    for s in sensibilidad:
        lineas.append(f"| {s['umbral_subrangos']} | {s['n_rapidas']} | "
                      f"{_f(s['mediana_partidas_dia_rapidas'])} | "
                      f"{_f(s['mediana_partidas_dia_resto'])} |")
    lineas += ["", "## Horas locales más frecuentes (top-3 por cuenta)", "",
               f"- rápidos: {salida['horas_top3']['rapidas'][:6]}",
               f"- resto: {salida['horas_top3']['resto'][:6]}"]
    with open(SALIDA_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")

    print(f"con historial {len(cuentas)} · con serie {len(con_serie)} · válidas {len(validas)}")
    print(f"rápidas {len(rapidas)} · resto {len(resto)} · literal3div {len(literal)} "
          f"· literal2div {len(literal_2div)} · 3div en toda la muestra {len(tres_div_todo)}")
    print(f"escrito: {SALIDA_JSON}\nescrito: {SALIDA_MD}")


def _f(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""El plan de antes de jugar: qué toca hoy, con tus números, no con consejos.

Por qué existe. Después de la partida ya hay `nota.py`, que dice cómo te fue. Antes de
jugarla no había nada: el jugador abría la cola sin saber qué estaba fallando ni con qué
referencia compararse. Este comando resume tus últimas partidas rankeadas de la temporada
y las pone contra las metas medidas:

    3 200 antes del minuto 12 · 6 muertes o menos · 0.40 de participación (k+a)/min

De dónde sale cada número, sin adornos:

- Partidas, resultado, kills, muertes, asistencias y duración: `match-history` de la API.
  Es lo único que necesita red, y se cachea 10 minutos.
- Minuto del primer 3 200: de las demos ya analizadas (`personal-demos.json`). Solo existe
  para las partidas con demo; con las demás no se inventa nada.

Uso:
    python3 herramientas/demos/plan.py
    python3 herramientas/demos/plan.py --n 20 --json
    python3 herramientas/demos/plan.py --sin-red      # solo con lo cacheado/cohorte

Códigos: 0 plan completo · 2 sin datos suficientes.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
TEMPORADA_2 = 1793908800     # 2026-11-05 20:00 UTC: el rango se reinicia por temporada
COHORTE = RAIZ / "informes" / "lab" / "personal-demos.json"
CACHE = RAIZ / "salida" / "plan_cache.json"
CACHE_S = 600
UA = "abrams-coach/0.9"

OBJETIVO = RAIZ / "salida" / "plan_actual.json"
OBJETIVO_HORAS = 24          # una sesión: si el objetivo cumple un día, se renueva
OBJETIVO_PARTIDAS = 5
OBJETIVO_NECESARIAS = 3

# Winrate medido de Abrams por banda de rango (badge = tier*10 + subrango), en
# `datos/historico.db`: 109 812 jugador-partida de partidas Normal. Fuente:
# `informes/lab/HEROES-PARCHE-2026-11-18.md`. (tasa, ic_bajo, ic_alto, n)
REFERENCIA_BANDA = {
    "baja": (55.2, 52.4, 58.1, 1166),     # badge < 61
    "media": (54.0, 51.0, 57.0, 936),     # badge 61-85
    "alta": (52.2, 49.0, 55.4, 806),      # badge >= 86
}
META_3200 = 12.0
META_MUERTES = 6
META_PART = 0.40


def cuenta(ruta=None) -> int | None:
    ruta = Path(ruta or os.path.expanduser("~/Desktop/Chat/abrams-coach/.cuenta"))
    if not ruta.exists():
        ruta = RAIZ / ".cuenta"
    try:
        valor = ruta.read_text(encoding="utf-8").strip()
        return int(valor) if valor.isdigit() else None
    except OSError:
        return None


def historial(acc: int, sin_red: bool = False) -> list[dict] | None:
    """Match-history completa, cacheada. None si no se pudo."""
    if CACHE.exists() and time.time() - CACHE.stat().st_mtime < CACHE_S:
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    if sin_red:
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    req = urllib.request.Request(f"https://api.deadlock-api.com/v1/players/{acc}/match-history",
                                 headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:      # noqa: S310
            datos = json.loads(r.read())
    except Exception:                                           # noqa: BLE001
        return None
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(datos), encoding="utf-8")
    except OSError:
        pass
    return datos


def rankeadas(datos: list[dict], desde: int = TEMPORADA_2) -> list[dict]:
    """Rankeadas del héroe Abrams y de la temporada, de la más nueva a la más vieja."""
    out = [x for x in datos
           if int(x.get("start_time") or 0) >= desde
           and x.get("match_mode") == 4
           and (x.get("match_duration_s") or 0) >= 600]
    out.sort(key=lambda x: -int(x.get("start_time") or 0))
    return out


def participacion(x: dict) -> float | None:
    dur = x.get("match_duration_s") or 0
    if dur <= 0:
        return None
    return (int(x.get("player_kills") or 0) + int(x.get("player_assists") or 0)) / (dur / 60)


def cohorte_3200() -> dict[int, float]:
    """Minuto del primer 3 200 por partida, de las demos ya medidas."""
    try:
        doc = json.loads(COHORTE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for p in doc.get("partidas") or []:
        m = p.get("min3200")
        if isinstance(m, (int, float)):
            out[int(p.get("match") or 0)] = float(m)
    return out


def banda(badge) -> str | None:
    try:
        b = int(badge)
    except (TypeError, ValueError):
        return None
    return "baja" if b < 61 else ("media" if b < 86 else "alta")


def referencia_badges(partidas: list[dict]) -> tuple[str | None, int | None]:
    """Banda y badge de la partida más reciente que lo traiga."""
    for x in partidas:
        b = x.get("ranked_display_badge")
        if b:
            return banda(b), int(b)
    return None, None


def resumir(partidas: list[dict], demos: dict[int, float]) -> dict:
    if not partidas:
        return {"n": 0}
    victorias = sum(1 for x in partidas if x.get("player_match_outcome") == 1)
    muertes = [int(x.get("player_deaths") or 0) for x in partidas]
    parts = [p for p in (participacion(x) for x in partidas) if p is not None]
    min3200 = [demos[int(x["match_id"])] for x in partidas if int(x["match_id"]) in demos]
    return {
        "n": len(partidas),
        "victorias": victorias,
        "derrotas": len(partidas) - victorias,
        "wr": round(100 * victorias / len(partidas), 1),
        "muertes_media": round(statistics.mean(muertes), 1) if muertes else None,
        "muertes_cumple": round(100 * sum(1 for m in muertes if m <= META_MUERTES) / len(muertes), 1),
        "part_media": round(statistics.mean(parts), 2) if parts else None,
        "part_cumple": round(100 * sum(1 for p in parts if p >= META_PART) / len(parts), 1) if parts else None,
        "min3200_mediana": round(statistics.median(min3200), 1) if min3200 else None,
        "min3200_n": len(min3200),
        "desde": datetime.fromtimestamp(min(int(x["start_time"]) for x in partidas)).strftime("%Y-%m-%d"),
        "hasta": datetime.fromtimestamp(max(int(x["start_time"]) for x in partidas)).strftime("%Y-%m-%d"),
    }


def enfoque(r: dict) -> tuple[str, str]:
    """Qué atacar primero, por tamaño de la brecha contra la meta."""
    brechas = []
    if r.get("muertes_media") is not None:
        brechas.append(("muertes", r["muertes_media"] - META_MUERTES,
                        "baja las muertes: cada partida por encima de 6 cambia el perfil"))
    if r.get("part_media") is not None:
        brechas.append(("participacion", META_PART - r["part_media"],
                        "entra a las peleas: asistencias, no farmeo"))
    # El 3 200 NO entra como enfoque: a escala el corte de 12 min no separa nada
    # (`informes/lab/REGLA-3200-2026-11-18.md`). Se mide como referencia, no se
    # convierte en tarea.
    if not brechas:
        return ("sin datos", "faltan datos para elegir un enfoque")
    clave, tam, texto = max(brechas, key=lambda x: x[1])
    if tam <= 0:
        return ("mantener", "vas dentro de las tres metas; el objetivo es no romperlas")
    return (clave, texto)


def texto(r: dict, e: tuple[str, str]) -> str:
    if not r.get("n"):
        return "Sin partidas rankeadas de la temporada: no hay plan que dar todavía."
    def marca(v, meta, mayor_mejor=False):
        if v is None:
            return "sin dato"
        ok = v >= meta if mayor_mejor else v <= meta
        return f"{v} {'✓' if ok else '✗'} (meta {'≥' if mayor_mejor else '≤'}{meta})"
    lineas = [
        f"Últimas {r['n']} ranked · {r['victorias']}V-{r['derrotas']}D · {r['wr']} % "
        f"· {r['desde']} → {r['hasta']}",
        f"  muertes:        {marca(r['muertes_media'], META_MUERTES)}"
        f"  · cumple el {r['muertes_cumple']} % de las partidas",
        f"  participación:  {marca(r['part_media'], META_PART, True)}"
        f"  · cumple el {r['part_cumple']} % de las partidas",
        f"  3 200:          {marca(r['min3200_mediana'], META_3200)}"
        f"  · medido en {r['min3200_n']} de {r['n']} (referencia, no meta: sin efecto"
        f" demostrado a escala)",
        "",
        f"Enfoque de hoy: {e[1]}",
    ]
    return "\n".join(lineas)


def texto_referencia(partidas: list[dict], r: dict) -> str:
    """Compara tu WR con el de Abrams en tu banda. Sin dato de banda, no se pinta."""
    b, badge = referencia_badges(partidas)
    if not b or not r.get("n"):
        return ""
    tasa, lo, hi, n = REFERENCIA_BANDA[b]
    n_txt = f"{n:,}".replace(",", " ")
    return (f"Referencia en tu banda ({b}, badge {badge}): Abrams gana {tasa} % "
            f"[{lo}; {hi}], n={n_txt} · tú {r['wr']} % en tus últimas {r['n']}")


# ------------------------------------------------------------------ objetivo de sesión
def _regla_del_enfoque(clave: str) -> str:
    """El enfoque se traduce en una regla que se pueda comprobar partida a partida."""
    return {"muertes": "muertes", "participacion": "participacion",
            "3 200": "min3200"}.get(clave, "muertes")


def crear_objetivo(regla: str, desde: float | None = None,
                   partidas: int = OBJETIVO_PARTIDAS,
                   necesarias: int = OBJETIVO_NECESARIAS) -> dict:
    return {"regla": regla, "meta": {"muertes": META_MUERTES, "participacion": META_PART,
                                     "min3200": META_3200}.get(regla),
            "partidas": partidas, "necesarias": necesarias,
            "desde": time.time() if desde is None else float(desde),
            "creado": datetime.now().strftime("%Y-%m-%d %H:%M")}


def cargar_objetivo() -> dict | None:
    try:
        doc = json.loads(OBJETIVO.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) and doc.get("regla") else None
    except (OSError, ValueError):
        return None


def guardar_objetivo(obj: dict) -> None:
    try:
        OBJETIVO.parent.mkdir(parents=True, exist_ok=True)
        OBJETIVO.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def cumple(x: dict, regla: str, demos: dict[int, float]) -> bool | None:
    """True/False si la partida cumple la regla; None si no hay dato para esa regla."""
    if regla == "muertes":
        d = x.get("player_deaths")
        return None if d is None else int(d) <= META_MUERTES
    if regla == "participacion":
        p = participacion(x)
        return None if p is None else p >= META_PART
    if regla == "min3200":
        m = demos.get(int(x.get("match_id") or 0))
        return None if m is None else m <= META_3200
    return None


def progreso(partidas: list[dict], obj: dict, demos: dict[int, float]) -> dict:
    desde = float(obj.get("desde") or 0)
    dentro = [x for x in partidas if float(x.get("start_time") or 0) >= desde]
    hechas = [x for x in dentro if cumple(x, obj["regla"], demos) is not None]
    si = sum(1 for x in hechas if cumple(x, obj["regla"], demos))
    return {"hechas": len(hechas), "cumplidas": si, "objetivo_partidas": obj["partidas"],
            "necesarias": obj["necesarias"],
            "logrado": si >= obj["necesarias"],
            "agotado": len(hechas) >= obj["partidas"]}


def texto_objetivo(obj: dict, prog: dict) -> str:
    etiqueta = {"muertes": f"≤{META_MUERTES} muertes",
                "participacion": f"≥{META_PART} k+a/min",
                "min3200": f"3 200 antes del min {int(META_3200)}"}.get(obj["regla"], obj["regla"])
    cola = ""
    if prog.get("logrado"):
        cola = " · objetivo cumplido, renueva con --nuevo"
    elif prog.get("agotado"):
        cola = " · sesión de 5 partidas cerrada sin cumplirlo; renueva con --nuevo"
    elif prog["hechas"] == 0 and obj["regla"] == "min3200":
        cola = " · el 3 200 se mide cuando llegue la demo"
    return (f"Objetivo de hoy: {obj['necesarias']} de {obj['partidas']} con {etiqueta} "
            f"· vas {prog['cumplidas']}/{prog['hechas']}{cola}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Plan de antes de jugar")
    ap.add_argument("--n", type=int, default=10, help="cuántas ranked recientes mirar")
    ap.add_argument("--cuenta", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sin-red", action="store_true")
    ap.add_argument("--nuevo", action="store_true", help="renueva el objetivo de la sesión")
    ap.add_argument("--progreso", action="store_true", help="solo muestra el objetivo")
    a = ap.parse_args(argv)

    acc = a.cuenta or cuenta()
    if not acc:
        print("no hay cuenta: falta .cuenta", file=sys.stderr)
        return 2
    datos = historial(acc, a.sin_red)
    if not datos:
        print("no pude leer el historial (sin red y sin caché)", file=sys.stderr)
        return 2
    partidas = rankeadas(datos)[:max(1, a.n)]
    demos = cohorte_3200()
    r = resumir(partidas, demos)
    e = enfoque(r)
    obj = None if a.nuevo else cargar_objetivo()
    if not obj or (time.time() - float(obj.get("desde") or 0)) > OBJETIVO_HORAS * 3600:
        obj = crear_objetivo(_regla_del_enfoque(e[0]))
        guardar_objetivo(obj)
    prog = progreso(partidas, obj, demos)
    if prog["logrado"] or prog["agotado"]:
        # La sesión se cerró: se renueva para la próxima, sin tocar el registro anterior.
        obj = crear_objetivo(_regla_del_enfoque(e[0]))
        guardar_objetivo(obj)
        prog = progreso(partidas, obj, demos)
    if a.json:
        print(json.dumps({"resumen": r, "enfoque": {"clave": e[0], "texto": e[1]},
                          "objetivo": obj, "progreso": prog},
                         ensure_ascii=False, indent=2))
    elif a.progreso:
        print(texto_objetivo(obj, prog))
    else:
        print(texto(r, e))
        ref = texto_referencia(partidas, r)
        if ref:
            print(ref)
        print(texto_objetivo(obj, prog))
    return 0 if r.get("n") else 2


if __name__ == "__main__":
    raise SystemExit(main())

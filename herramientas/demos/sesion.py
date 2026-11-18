#!/usr/bin/env python3
"""Cómo fue la sesión: lee las notas archivadas y saca el patrón.

`nota.py --guardar` deja una nota por partida en `salida/notas/<match>.json`. Este comando
lee las de las últimas horas (o todas con `--todo`) y responde a la única pregunta que
importa al cerrar el juego: **¿qué regla se me fue y cuánto**.

Nada de esto se inventa: si no hay notas, lo dice. Las métricas salen de las partidas ya
analizadas; las que no tenían demo cuentan para muertes y participación, no para el 3 200.

Uso:
    python3 herramientas/demos/sesion.py
    python3 herramientas/demos/sesion.py --horas 48
    python3 herramientas/demos/sesion.py --todo --json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
NOTAS = RAIZ / "salida" / "notas"

REGLAS = (("min3200", "3 200 antes del min 12"),
          ("muertes", "6 muertes o menos"),
          ("participacion", "≥0.40 k+a/min"))
# Solo estas dos tienen efecto demostrado (3 538 partidas): el 3 200 se informa, pero no
# se propone como tarea (`informes/lab/REGLA-3200-2026-11-18.md`).
REGLAS_CON_EFECTO = ("muertes", "participacion")


def cargar(carpeta=None, horas: float | None = 24.0) -> list[dict]:
    carpeta = Path(carpeta or NOTAS)
    limite = time.time() - horas * 3600 if horas else None
    out = []
    try:
        archivos = sorted(carpeta.glob("*.json"))
    except OSError:
        return []
    for ruta in archivos:
        try:
            if limite and ruta.stat().st_mtime < limite:
                continue
            doc = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("match_id"):
            out.append(doc)
    return out


def resumir(notas: list[dict]) -> dict:
    if not notas:
        return {"n": 0}
    victorias = sum(1 for x in notas if x.get("gane") is True)
    derrotas = sum(1 for x in notas if x.get("gane") is False)
    muertes = [x["metricas"]["muertes"] for x in notas
               if isinstance(x.get("metricas"), dict) and x["metricas"].get("muertes") is not None]
    parts = [x["metricas"]["participacion"] for x in notas
             if isinstance(x.get("metricas"), dict)
             and x["metricas"].get("participacion") is not None]
    por_regla = {}
    for clave, _ in REGLAS:
        hechas = [r for x in notas for r in (x.get("reglas") or [])
                  if r.get("clave") == clave and r.get("cumple") is not None]
        por_regla[clave] = {"evaluadas": len(hechas),
                            "cumplidas": sum(1 for r in hechas if r.get("cumple") is True)}
    return {
        "n": len(notas),
        "victorias": victorias,
        "derrotas": derrotas,
        "wr": round(100 * victorias / len(notas), 1),
        "muertes_media": round(statistics.mean(muertes), 1) if muertes else None,
        "part_media": round(statistics.mean(parts), 2) if parts else None,
        "por_regla": por_regla,
    }


def foco(r: dict) -> tuple[str, str] | None:
    """La regla con peor cumplimiento relativo, si hay muestra para decirlo."""
    peor = None
    for clave, texto in REGLAS:
        if clave not in REGLAS_CON_EFECTO:
            continue
        d = r.get("por_regla", {}).get(clave) or {}
        if not d.get("evaluadas"):
            continue
        pct = 100 * d["cumplidas"] / d["evaluadas"]
        if peor is None or pct < peor[0]:
            peor = (pct, texto, d)
    if peor is None or peor[2]["cumplidas"] == peor[2]["evaluadas"]:
        return None
    pct, texto, d = peor
    return (texto, f"{texto}: {d['cumplidas']}/{d['evaluadas']} ({pct:.0f} %)")


def texto(r: dict, f: tuple[str, str] | None) -> str:
    if not r.get("n"):
        return "Sin notas en la ventana: no hay sesión que resumir."
    n = r["n"]
    plural = "s" if n != 1 else ""
    lineas = [f"Sesión: {n} partida{plural} · {r['victorias']}V-{r['derrotas']}D · {r['wr']} %"]
    if r["muertes_media"] is not None:
        lineas.append(f"  muertes:       {r['muertes_media']} de media (meta ≤6)")
    if r["part_media"] is not None:
        lineas.append(f"  participación: {r['part_media']} de media (meta ≥0.40)")
    for clave, nombre in REGLAS:
        d = r["por_regla"].get(clave) or {}
        if d.get("evaluadas"):
            # «sin dato» casi siempre es «la demo de esa partida no estaba»: se dice, no
            # se cuenta como incumplida.
            sin_dato = n - d["evaluadas"]
            extra = f" · {sin_dato} sin dato" if sin_dato else ""
            lineas.append(f"  {nombre}: {d['cumplidas']}/{d['evaluadas']}{extra}")
        elif n:
            # Regla que no se pudo evaluar en ninguna partida (sin demo, casi siempre).
            lineas.append(f"  {nombre}: sin dato")
    if f:
        lineas.append(f"Lo que más se te fue: {f[1]}")
    return "\n".join(lineas)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Resumen de la sesión desde las notas")
    ap.add_argument("--horas", type=float, default=24.0)
    ap.add_argument("--todo", action="store_true", help="sin filtro de tiempo")
    ap.add_argument("--dir", default=str(NOTAS))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    notas = cargar(a.dir, None if a.todo else a.horas)
    r = resumir(notas)
    f = foco(r)
    if a.json:
        print(json.dumps({"resumen": r, "foco": f[0] if f else None},
                         ensure_ascii=False, indent=1))
    else:
        print(texto(r, f))
    return 0 if r.get("n") else 2


if __name__ == "__main__":
    sys.exit(main())

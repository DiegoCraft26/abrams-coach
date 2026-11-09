#!/usr/bin/env python3
"""Resumen de la última partida, sin abrir la app y sin llamar a nadie.

Junta lo que quedó en disco y lo cuenta en cinco líneas: qué partida se creyó, por qué
vía, cuántos cuadros y tokens gastó la visión, cuántas decisiones se registraron y qué
avisos dio el coach. Es la forma de responder «¿esto sirvió de algo?» después de jugar.

Uso:
    python3 herramientas/resumen_partida.py
    python3 herramientas/resumen_partida.py --json
"""
import argparse
import json
import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import telemetria  # noqa: E402


def _leer_json(ruta: str) -> dict:
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _contar_lineas(ruta: str) -> int:
    try:
        with open(ruta, encoding="utf-8") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _hora(ts: float) -> str:
    try:
        return time.strftime("%H:%M:%S", time.localtime(float(ts)))
    except (TypeError, ValueError):
        return "—"


def resumen() -> dict:
    identidad = telemetria.resumen()
    uso = _leer_json(os.path.join(RAIZ, "salida", "vision_uso.json"))
    decisiones = _contar_lineas(os.path.join(RAIZ, "salida", "decisiones.jsonl"))
    ultimo = identidad.get("ultimo") or {}
    return {
        "match": ultimo.get("match"),
        "via": ultimo.get("via"),
        "detalle": ultimo.get("detalle"),
        "cuando": _hora(ultimo.get("ts")),
        "eventos_identidad": identidad.get("eventos"),
        "por_via": identidad.get("por_via"),
        "rechazos": identidad.get("rechazos"),
        "vision_cuadros": uso.get("cuadros"),
        "vision_tope": uso.get("tope"),
        "vision_tokens": uso.get("tokens"),
        "vision_fallos": uso.get("fallos"),
        "decisiones": decisiones,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="el resumen crudo, sin texto")
    a = ap.parse_args()
    datos = resumen()
    if a.json:
        print(json.dumps(datos, ensure_ascii=False, indent=1))
        return 0

    print("Abrams Coach · última actividad")
    print(f"  partida    {datos['match']} · vía {datos['via'] or '—'} · {datos['cuando']}")
    if datos["detalle"]:
        print(f"             {datos['detalle']}")
    vias = ", ".join(f"{k} {v}" for k, v in (datos["por_via"] or {}).items()) or "—"
    print(f"  identidad  {datos['eventos_identidad']} decisiones ({vias}); "
          f"{datos['rechazos']} rechazos")
    if datos["vision_cuadros"] is None:
        print("  visión     sin consumo registrado")
    else:
        print(f"  visión     {datos['vision_cuadros']}/{datos['vision_tope']} cuadros · "
              f"{datos['vision_tokens']} tokens · {datos['vision_fallos']} fallos")
    print(f"  registro   {datos['decisiones']} líneas en salida/decisiones.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())

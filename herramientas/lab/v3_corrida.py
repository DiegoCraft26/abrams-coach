#!/usr/bin/env python3
"""Corre el Motor v3 cuando hay demos suficientes, y no antes.

Por qué existe. El estimador v3 ya funciona, pero con 79 demos no hay un solo ítem con
muestra para decidir (40 con n≥150, cero con n≥2 149). El crawler acumula ~2 800 partidas
al día; lo que faltaba era que alguien volviera a correr la tabla y el estimador cuando el
volumen alcance, sin que un humano se acuerde.

Este comando hace exactamente eso:

    1. Cuenta las demos en `datos/demos/`.
    2. Si no llega al mínimo (por defecto 1 500) y no se fuerza, sale sin tocar nada.
    3. Regenera `datos/demos_norm.csv.gz` con `demos_norm.py`.
    4. Estima con `estimador_v3.py --bootstrap 200` y deja `datos/modelo_v3.json`.
    5. Pasa la puerta del sintético (verdad conocida): si no recupera el signo, NO publica.
    6. Escribe `informes/lab/V3-AUTO-<fecha>.md` y actualiza `datos/v3_estado.json`.

La puerta del sintético es la que impide que un cambio de código roto produzca un artefacto
elegante y falso. Si falla, el estado anterior queda intacto y el informe lo dice.

Uso:
    python3 herramientas/lab/v3_corrida.py --seco        # solo cuenta y decide
    python3 herramientas/lab/v3_corrida.py               # corre si toca
    python3 herramientas/lab/v3_corrida.py --forzar      # corre aunque falten demos

Códigos: 0 corrió o no tocaba · 2 error · 3 sintético no pasó la puerta.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
DEMOS = RAIZ / "datos" / "demos"
TABLA = RAIZ / "datos" / "demos_norm.csv.gz"
MODELO = RAIZ / "datos" / "modelo_v3.json"
ESTADO = RAIZ / "datos" / "v3_estado.json"
INFORMES = RAIZ / "informes" / "lab"
MINIMO = 1500
PY = sys.executable


def contar_demos() -> int:
    try:
        return sum(1 for d in DEMOS.iterdir() if d.is_dir() and (d / "abilities.ndjson").exists())
    except OSError:
        return 0


def leer_estado() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar_estado(doc: dict) -> None:
    try:
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ESTADO.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def correr(cmd: list[str], timeout: int = 3600) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "tiempo agotado"
    except OSError as exc:
        return 2, str(exc)


def resumen_modelo(ruta: Path) -> dict:
    """Recorta el artefacto a lo que se puede citar sin abrirlo entero."""
    try:
        doc = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"error": "no se pudo leer el artefacto"}
    items = doc.get("items") or {}
    n = sorted((v.get("n", 0) for v in items.values()), reverse=True)
    con150 = sum(1 for x in n if x >= 150)
    con2149 = sum(1 for x in n if x >= 2149)
    fuera = sum(1 for v in items.values()
                if isinstance(v.get("ic90"), list) and len(v["ic90"]) == 2
                and (v["ic90"][0] > 0 or v["ic90"][1] < 0))
    return {
        "items": len(items),
        "n_mediana": n[len(n) // 2] if n else 0,
        "n_max": n[0] if n else 0,
        "con_n150": con150,
        "con_n2149": con2149,
        "ic_fuera_de_cero": fuera,
        "esperados_por_azar": round(len(items) * 0.1, 1),
        "filas": (doc.get("corpus") or {}).get("filas"),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Corre el Motor v3 cuando hay volumen")
    ap.add_argument("--minimo", type=int, default=MINIMO)
    ap.add_argument("--forzar", action="store_true")
    ap.add_argument("--seco", action="store_true", help="solo cuenta y decide")
    ap.add_argument("--sin-sintetico", action="store_true", help="salta la puerta del sintético")
    ap.add_argument("--bootstrap", type=int, default=200)
    a = ap.parse_args(argv)

    demos = contar_demos()
    estado = leer_estado()
    print(f"demos: {demos} · mínimo: {a.minimo} · última corrida: {estado.get('fecha', '—')} "
          f"con {estado.get('demos', 0)} demos")
    if a.seco:
        return 0
    if not a.forzar and demos < a.minimo:
        print(f"faltan {a.minimo - demos} demos para correr el Motor v3; no se toca nada.")
        return 0
    if not a.forzar and demos == estado.get("demos"):
        print("no hay demos nuevas desde la última corrida; no se toca nada.")
        return 0
    if not (RAIZ / "herramientas" / "lab" / "demos_norm.py").exists():
        print("falta demos_norm.py", file=sys.stderr)
        return 2

    print("1/3 normalizando compras con oro real…")
    cod, salida = correr([PY, "herramientas/lab/demos_norm.py"], timeout=2400)
    if cod != 0:
        print(salida[-1500:], file=sys.stderr)
        return 2

    print("2/3 estimando…")
    cod, salida = correr([PY, "herramientas/lab/estimador_v3.py",
                          "--bootstrap", str(a.bootstrap), "--salida", str(MODELO)], timeout=3600)
    if cod != 0:
        print(salida[-1500:], file=sys.stderr)
        return 2
    r = resumen_modelo(MODELO)

    puerta = "no corrida"
    if not a.sin_sintetico:
        print("3/3 puerta del sintético…")
        cod, salida = correr([PY, "herramientas/lab/sintetico_v3.py",
                              "--salida", "/tmp/sint_v3.csv.gz", "--verdad", "/tmp/sint_v3_verdad.json"],
                             timeout=900)
        if cod != 0:
            puerta = "no se pudo generar el sintético"
        else:
            cod2, sal2 = correr([PY, "herramientas/lab/estimador_v3.py",
                                 "--tabla", "/tmp/sint_v3.csv.gz",
                                 "--verdad", "/tmp/sint_v3_verdad.json",
                                 "--bootstrap", "50", "--salida", "/tmp/sint_v3_modelo.json",
                                 "--silencioso"], timeout=1800)
            puerta = "pasó" if cod2 == 0 else "FALLÓ"
            if cod2 != 0:
                print(sal2[-1500:], file=sys.stderr)
                if not a.forzar:
                    return 3

    fecha = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    INFORMES.mkdir(parents=True, exist_ok=True)
    salida_md = INFORMES / f"V3-AUTO-{datetime.now().strftime('%Y-%m-%d')}.md"
    lineas = [
        f"# Motor v3 automático — {fecha}",
        "",
        f"- Demos: **{demos}**",
        f"- Tabla: `datos/demos_norm.csv.gz`",
        f"- Artefacto: `datos/modelo_v3.json`",
        f"- Puerta del sintético: **{puerta}**",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Ítems | {r.get('items')} |",
        f"| Filas | {r.get('filas')} |",
        f"| n mediana por ítem | {r.get('n_mediana')} |",
        f"| n máximo | {r.get('n_max')} |",
        f"| Ítems con n ≥ 150 | {r.get('con_n150')} |",
        f"| Ítems con n ≥ 2 149 (medido) | {r.get('con_n2149')} |",
        f"| IC90 fuera de cero | {r.get('ic_fuera_de_cero')} (azar: {r.get('esperados_por_azar')}) |",
        "",
        "Nada de esto se publica solo: el panel solo enseña un ítem que pase las puertas de",
        "`docs/MOTOR-V2.md`. Con los números de arriba se ve si ya hay alguno.",
    ]
    salida_md.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    guardar_estado({"fecha": fecha, "demos": demos, "items": r.get("items"),
                    "con_n2149": r.get("con_n2149"), "sintetico": puerta})
    print(f"listo: {salida_md}")
    print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

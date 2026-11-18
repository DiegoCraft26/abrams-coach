#!/usr/bin/env python3
"""Ejemplo de consulta sobre lo que guardó `crawler.py`.

Para cada uno de los 12 slots busca **la primera compra de 3 200** (el primer evento
`CurrencyChangedEvent` con `delta = -3200` y `currency_type = 0`) y cruza el tick con
`AbilitiesChangedEvent` para saber qué habilidad/ítem se compró. Devuelve el oro real
antes y después, tal como lo registra la demo.

El oro bruto del evento es `new_value` (oro después); `delta` es el cambio, así que
`oro_antes = new_value - delta`.

Sin `--match` elige la partida de `datos/demos/` con más slots que tengan esa compra
(ideal: 12 de 12). Lee solo NDJSON, no toca la red.

Uso:
    python3 herramientas/demos/ejemplo_oro.py --match 139680544
    python3 herramientas/demos/ejemplo_oro.py --elegir --json /tmp/ejemplo.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
TPS = 64
COSTE = 3200


def leer_ndjson(ruta: Path) -> list[dict]:
    filas: list[dict] = []
    if not ruta.exists():
        return filas
    with open(ruta, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                filas.append(json.loads(linea))
    return filas


def primera_compra(compras: list[dict], oro: list[dict], slot: int) -> dict | None:
    candidatos = sorted(
        (r for r in oro
         if int(r.get("userid", -99)) == slot
         and int(r.get("currency_type", -1)) == 0
         and int(r.get("delta", 0)) == -COSTE),
        key=lambda r: int(r["tick"]),
    )
    if not candidatos:
        return None
    evento = candidatos[0]
    tick = int(evento["tick"])
    # La compra deja el evento de habilidad en el mismo tick (a veces ±1).
    cerca = [
        c for c in compras
        if int(c.get("purchaser_player_slot", -99)) == slot
        and int(c.get("change", -1)) == 0
        and abs(int(c["tick"]) - tick) <= 3
    ]
    habilidad = min(cerca, key=lambda c: abs(int(c["tick"]) - tick)) if cerca else None
    return {
        "slot": slot,
        "tick": tick,
        "minuto": round(tick / TPS / 60.0, 1),
        "ability_id": int(habilidad["ability_id"]) if habilidad else None,
        "oro_antes": int(evento["new_value"]) - int(evento["delta"]),
        "oro_despues": int(evento["new_value"]),
        "delta": int(evento["delta"]),
    }


def analizar(carpeta: Path) -> dict:
    compras = leer_ndjson(carpeta / "abilities.ndjson")
    oro = leer_ndjson(carpeta / "currency_gold.ndjson")
    filas = [f for f in (primera_compra(compras, oro, s) for s in range(12)) if f]
    return {
        "match_id": carpeta.name,
        "slots_con_3200": len(filas),
        "filas": filas,
    }


def elegir(datos: Path) -> Path:
    mejores: list[tuple[int, int, Path]] = []
    for carpeta in datos.iterdir():
        if not carpeta.is_dir():
            continue
        if not (carpeta / "abilities.ndjson").exists():
            continue
        if not (carpeta / "currency_gold.ndjson").exists():
            continue
        resultado = analizar(carpeta)
        mejores.append((resultado["slots_con_3200"], len(resultado["filas"]), carpeta))
    if not mejores:
        raise SystemExit(f"no hay partidas procesadas en {datos}")
    mejores.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return mejores[0][2]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("Uso:", 1)[0].strip())
    p.add_argument("--match", default="", help="id de partida ya extraída")
    p.add_argument("--datos", default=str(RAIZ / "datos" / "demos"), help="carpeta del crawler")
    p.add_argument("--elegir", action="store_true", help="elige la partida con más slots")
    p.add_argument("--json", default="", help="escribe el resultado en JSON")
    args = p.parse_args(argv)

    datos = Path(args.datos).expanduser().resolve()
    if args.match:
        carpeta = datos / args.match
    elif args.elegir:
        carpeta = elegir(datos)
    else:
        p.error("hace falta --match o --elegir")
    if not (carpeta / "currency_gold.ndjson").exists():
        raise SystemExit(f"no está extraída: {carpeta}")

    resultado = analizar(carpeta)
    print(f"partida {resultado['match_id']}: {resultado['slots_con_3200']}/12 slots "
          f"con primera compra de {COSTE}")
    print(f"{'slot':>4} {'tick':>7} {'min':>6} {'ability_id':>12} "
          f"{'oro_antes':>10} {'oro_despues':>11}")
    for f in resultado["filas"]:
        print(f"{f['slot']:>4} {f['tick']:>7} {f['minuto']:>6.1f} "
              f"{str(f['ability_id']):>12} {f['oro_antes']:>10} {f['oro_despues']:>11}")
    if args.json:
        destino = Path(args.json).expanduser()
        destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=1),
                           encoding="utf-8")
        print(f"-> {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

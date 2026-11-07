"""CLI idempotente para archivar logs y artefactos en SQLite."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterator

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from coach.persistencia.db import conectar, migrar, resolver_ruta_db
from coach.persistencia.repos import (
    Compra,
    Muestra,
    Partida,
    Recomendacion,
    guardar_compra,
    guardar_muestra,
    guardar_partida,
    guardar_recomendacion,
)


def _entero(valor: Any, defecto: int | None = None) -> int | None:
    try:
        if valor is None or valor == "":
            return defecto
        return int(valor)
    except (TypeError, ValueError):
        return defecto


def _flotante(valor: Any, defecto: float | None = None) -> float | None:
    try:
        if valor is None or valor == "":
            return defecto
        return float(valor)
    except (TypeError, ValueError):
        return defecto


def _texto(valor: Any) -> str | None:
    if valor is None:
        return None
    texto = str(valor)
    return texto


def _iter_jsonl(ruta: Path) -> Iterator[dict[str, Any]]:
    if not ruta.exists():
        return
    with ruta.open("r", encoding="utf-8") as archivo:
        for linea in archivo:
            linea = linea.strip()
            if not linea:
                continue
            try:
                dato = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if isinstance(dato, dict):
                yield dato


def _match_desde_nombre(ruta: Path) -> int | None:
    nombre = ruta.stem
    m = re.search(r"monitor[-_](\d+)", nombre, re.IGNORECASE)
    if m:
        return int(m.group(1))
    numeros = [int(n) for n in re.findall(r"\d+", nombre)]
    if not numeros:
        return None
    largos = [n for n in numeros if n >= 100000]
    if largos:
        return largos[-1]
    return numeros[-1]


def _resolver_match(dato: dict[str, Any], ruta: Path, sin_match: dict[str, int], origen: str) -> int:
    match_id = _entero(dato.get("match_id"))
    if match_id is None:
        match_id = _entero(dato.get("match"))
    if match_id is None:
        match_id = _match_desde_nombre(ruta)
    if match_id is None:
        sin_match[origen] = sin_match.get(origen, 0) + 1
        return 0
    return match_id


def _asegurar_partida(conexion, match_id: int, heroe: str | None = None) -> int:
    if match_id == 0:
        return 0
    return guardar_partida(conexion, Partida(match_id=match_id, heroe=heroe))


def importar_decisiones(conexion, salida: Path, sin_match: dict[str, int]) -> dict[str, int]:
    nuevas = {"muestras": 0, "recomendaciones": 0, "partidas": 0}
    ruta = salida / "decisiones.jsonl"
    for dato in _iter_jsonl(ruta):
        match_id = _resolver_match(dato, ruta, sin_match, "decisiones")
        ts = _flotante(dato.get("ts"))
        if ts is None:
            continue
        nuevas["partidas"] += _asegurar_partida(conexion, match_id, _texto(dato.get("heroe")))
        recs_obj = dato.get("recomendaciones")
        recs_nombres = dato.get("recomendado")
        recs_json = None
        items: list[tuple[str, int | None, int | None, str | None]] = []
        if isinstance(recs_obj, list):
            recs_json = json.dumps(recs_obj, ensure_ascii=False)
            for rec in recs_obj:
                if isinstance(rec, dict):
                    nombre = _texto(rec.get("nombre") or rec.get("item") or rec.get("id"))
                    if not nombre:
                        continue
                    costo = _entero(rec.get("costo"))
                    razones = rec.get("razones")
                    razon = None
                    if isinstance(razones, list):
                        razon = "; ".join(str(r) for r in razones if r is not None)
                    elif razones is not None:
                        razon = str(razones)
                    alcanzable = rec.get("alcanzable")
                    if alcanzable is None and costo is not None:
                        almas = _entero(dato.get("almas"))
                        oro = _entero(dato.get("oro"))
                        bolsa = almas if almas is not None else oro
                        if bolsa is not None:
                            alcanzable = 1 if bolsa >= costo else 0
                    items.append((nombre, costo, _entero(alcanzable), razon))
        if isinstance(recs_nombres, list) and not items:
            recs_json = json.dumps(recs_nombres, ensure_ascii=False)
            for nombre in recs_nombres:
                if nombre is not None:
                    items.append((str(nombre), None, None, None))
        nuevas["muestras"] += guardar_muestra(
            conexion,
            Muestra(
                match_id=match_id,
                ts=ts,
                t=_flotante(dato.get("t")),
                estado=_texto(dato.get("estado")),
                almas=_entero(dato.get("almas")),
                oro=_entero(dato.get("oro")),
                delta=_flotante(dato.get("delta")),
                recs_json=recs_json,
            ),
        )
        for nombre, costo, alcanzable, razon in items:
            nuevas["recomendaciones"] += guardar_recomendacion(
                conexion,
                Recomendacion(
                    match_id=match_id,
                    ts=ts,
                    item=nombre,
                    costo=costo,
                    alcanzable=alcanzable,
                    razon=razon,
                ),
            )
    return nuevas


def importar_monitores(conexion, salida: Path, sin_match: dict[str, int]) -> dict[str, int]:
    nuevas = {"muestras": 0, "recomendaciones": 0, "partidas": 0}
    for ruta in sorted(salida.glob("monitor-*.jsonl")):
        for dato in _iter_jsonl(ruta):
            match_id = _resolver_match(dato, ruta, sin_match, "monitor")
            ts = _flotante(dato.get("ts"))
            if ts is None:
                continue
            nuevas["partidas"] += _asegurar_partida(conexion, match_id)
            recs = dato.get("recs")
            recs_json = json.dumps(recs, ensure_ascii=False) if recs is not None else None
            nuevas["muestras"] += guardar_muestra(
                conexion,
                Muestra(
                    match_id=match_id,
                    ts=ts,
                    t=_flotante(dato.get("t")),
                    estado=_texto(dato.get("estado")),
                    almas=_entero(dato.get("almas")),
                    oro=_entero(dato.get("oro")),
                    delta=_flotante(dato.get("delta")),
                    recs_json=recs_json,
                ),
            )
            if isinstance(recs, list):
                for rec in recs:
                    if isinstance(rec, (list, tuple)) and rec:
                        nombre = _texto(rec[0])
                        costo = _entero(rec[1]) if len(rec) > 1 else None
                        alcanzable_raw = rec[2] if len(rec) > 2 else None
                        alcanzable = 1 if alcanzable_raw is True else 0 if alcanzable_raw is False else _entero(alcanzable_raw)
                        razon = _texto(rec[3]) if len(rec) > 3 else None
                    elif isinstance(rec, dict):
                        nombre = _texto(rec.get("nombre") or rec.get("item") or rec.get("id"))
                        costo = _entero(rec.get("costo"))
                        alcanzable = _entero(rec.get("alcanzable"))
                        razon = _texto(rec.get("razon"))
                    else:
                        continue
                    if not nombre:
                        continue
                    nuevas["recomendaciones"] += guardar_recomendacion(
                        conexion,
                        Recomendacion(
                            match_id=match_id,
                            ts=ts,
                            item=nombre,
                            costo=costo,
                            alcanzable=alcanzable,
                            razon=razon,
                        ),
                    )
    return nuevas


def importar_compras(conexion, salida: Path, sin_match: dict[str, int]) -> dict[str, int]:
    nuevas = {"compras": 0, "partidas": 0}
    ruta = salida / "compras.jsonl"
    for dato in _iter_jsonl(ruta):
        match_id = _resolver_match(dato, ruta, sin_match, "compras")
        ts = _flotante(dato.get("ts"))
        if ts is None:
            continue
        nuevas["partidas"] += _asegurar_partida(conexion, match_id, _texto(dato.get("heroe")))
        nuevas["compras"] += guardar_compra(
            conexion,
            Compra(
                match_id=match_id,
                ts=ts,
                cuenta=_entero(dato.get("cuenta")),
                heroe=_texto(dato.get("heroe")),
                item=_texto(dato.get("item") or dato.get("nombre")),
                item_id=_texto(dato.get("item_id") or dato.get("id")),
            ),
        )
    return nuevas


def importar_videos(conexion, grabaciones: Path) -> dict[str, int]:
    nuevas = {"videos": 0, "partidas": 0}
    if not grabaciones.exists():
        return nuevas
    for ruta in sorted(grabaciones.iterdir()):
        if not ruta.is_file():
            continue
        try:
            st = ruta.stat()
        except OSError:
            continue
        match_id = _match_desde_nombre(ruta) or 0
        nuevas["partidas"] += _asegurar_partida(conexion, match_id)
        antes = conexion.total_changes
        conexion.execute(
            "INSERT OR IGNORE INTO videos (ruta, bytes, mtime, match_id) VALUES (?, ?, ?, ?)",
            (str(ruta.resolve()), int(st.st_size), float(st.st_mtime), match_id),
        )
        nuevas["videos"] += conexion.total_changes - antes
    return nuevas


def archivar(db: str | None, salida: Path) -> dict[str, int | dict[str, int]]:
    conexion = conectar(db)
    try:
        migrar(conexion)
        sin_match: dict[str, int] = {}
        totales: dict[str, int] = {
            "partidas": 0,
            "muestras": 0,
            "recomendaciones": 0,
            "compras": 0,
            "videos": 0,
        }
        for parcial in (
            importar_decisiones(conexion, salida, sin_match),
            importar_monitores(conexion, salida, sin_match),
            importar_compras(conexion, salida, sin_match),
            importar_videos(conexion, salida.parent / "grabaciones"),
        ):
            for tabla, cuenta in parcial.items():
                totales[tabla] = totales.get(tabla, 0) + int(cuenta)
        conexion.commit()
        return {"nuevas": totales, "sin_match_id": sin_match, "db": str(resolver_ruta_db(db))}
    finally:
        conexion.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Archiva logs del coach en SQLite.")
    parser.add_argument("--db", help="Ruta de la base de datos SQLite")
    parser.add_argument(
        "--salida",
        default=str(RAIZ / "salida"),
        help="Carpeta de salida con JSONL (por defecto: <repo>/salida)",
    )
    args = parser.parse_args(argv)
    resultado = archivar(args.db, Path(args.salida))
    nuevas = resultado["nuevas"]
    print(f"base: {resultado['db']}")
    for tabla in ("partidas", "muestras", "recomendaciones", "compras", "videos"):
        print(f"{tabla}: {nuevas.get(tabla, 0)} filas nuevas")
    sin_match = resultado["sin_match_id"]
    if sin_match:
        detalle = ", ".join(f"{k}={v}" for k, v in sorted(sin_match.items()))
        print(f"sin_match_id: {detalle}")
    else:
        print("sin_match_id: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Dataclasses y repositorios de persistencia."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass
class Partida:
    match_id: int
    inicio: str | None = None
    fin: str | None = None
    duracion_s: int | None = None
    heroe: str | None = None
    resultado: str | None = None
    video: str | None = None


@dataclass
class Muestra:
    match_id: int
    ts: float
    t: float | None = None
    estado: str | None = None
    almas: int | None = None
    oro: int | None = None
    delta: float | None = None
    recs_json: str | None = None


@dataclass
class Compra:
    match_id: int
    ts: float
    cuenta: int | None = None
    heroe: str | None = None
    item: str | None = None
    item_id: str | None = None


@dataclass
class Recomendacion:
    match_id: int
    ts: float
    item: str
    costo: int | None = None
    alcanzable: int | None = None
    razon: str | None = None


@dataclass
class Resultado:
    match_id: int
    win: int | None = None
    duracion_s: int | None = None
    kda: str | None = None
    fuente: str | None = None


def _cambios(conexion: sqlite3.Connection) -> int:
    fila = conexion.execute("SELECT changes()").fetchone()
    return int(fila[0]) if fila else 0


def guardar_partida(conexion: sqlite3.Connection, partida: Partida) -> int:
    conexion.execute(
        """
        INSERT OR IGNORE INTO partidas
            (match_id, inicio, fin, duracion_s, heroe, resultado, video)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            partida.match_id,
            partida.inicio,
            partida.fin,
            partida.duracion_s,
            partida.heroe,
            partida.resultado,
            partida.video,
        ),
    )
    return _cambios(conexion)


def guardar_muestra(conexion: sqlite3.Connection, muestra: Muestra) -> int:
    conexion.execute(
        """
        INSERT OR IGNORE INTO muestras
            (match_id, ts, t, estado, almas, oro, delta, recs_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            muestra.match_id,
            muestra.ts,
            muestra.t,
            muestra.estado,
            muestra.almas,
            muestra.oro,
            muestra.delta,
            muestra.recs_json,
        ),
    )
    return _cambios(conexion)


def guardar_compra(conexion: sqlite3.Connection, compra: Compra) -> int:
    conexion.execute(
        """
        INSERT OR IGNORE INTO compras
            (match_id, ts, cuenta, heroe, item, item_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            compra.match_id,
            compra.ts,
            compra.cuenta,
            compra.heroe,
            compra.item,
            compra.item_id,
        ),
    )
    return _cambios(conexion)


def guardar_recomendacion(
    conexion: sqlite3.Connection, recomendacion: Recomendacion
) -> int:
    conexion.execute(
        """
        INSERT OR IGNORE INTO recomendaciones
            (match_id, ts, item, costo, alcanzable, razon)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            recomendacion.match_id,
            recomendacion.ts,
            recomendacion.item,
            recomendacion.costo,
            recomendacion.alcanzable,
            recomendacion.razon,
        ),
    )
    return _cambios(conexion)


def guardar_resultado(conexion: sqlite3.Connection, resultado: Resultado) -> int:
    conexion.execute(
        """
        INSERT OR IGNORE INTO resultados
            (match_id, win, duracion_s, kda, fuente)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            resultado.match_id,
            resultado.win,
            resultado.duracion_s,
            resultado.kda,
            resultado.fuente,
        ),
    )
    return _cambios(conexion)


def log_agente(
    conexion: sqlite3.Connection,
    ts: float | None,
    pregunta: str | None,
    herramientas: str | list[Any] | None,
    respuesta: str | None,
    tokens: int | None,
) -> int:
    if herramientas is not None and not isinstance(herramientas, str):
        herramientas = json.dumps(herramientas, ensure_ascii=False)
    conexion.execute(
        """
        INSERT INTO agente_log (ts, pregunta, herramientas, respuesta, tokens)
        VALUES (?, ?, ?, ?, ?)
        """,
        (ts, pregunta, herramientas, respuesta, tokens),
    )
    conexion.commit()
    return _cambios(conexion)


def ultimas_partidas(conexion: sqlite3.Connection, n: int) -> list[dict[str, Any]]:
    cursor = conexion.execute(
        """
        SELECT p.*, r.win, r.kda
        FROM partidas p
        LEFT JOIN resultados r ON r.match_id = p.match_id
        ORDER BY COALESCE(p.fin, p.inicio, '') DESC, p.id DESC
        LIMIT ?
        """,
        (int(n),),
    )
    return [dict(fila) for fila in cursor.fetchall()]


def winrate_por_primer_item(conexion: sqlite3.Connection) -> list[dict[str, Any]]:
    """Winrate por primer ítem observado en partidas con resultado conocido.

    Prioriza compras (ts mínimo) y, si no hay compras para la partida, usa la
    primera recomendación registrada. Solo cuenta partidas presentes en
    `resultados` con `win` no nulo.
    """
    cursor = conexion.execute(
        """
        WITH partidas_con_win AS (
            SELECT match_id, win FROM resultados WHERE win IS NOT NULL
        ),
        primer_compra AS (
            SELECT c.match_id, c.item AS item
            FROM compras c
            JOIN partidas_con_win w ON w.match_id = c.match_id
            WHERE c.item IS NOT NULL AND c.item <> ''
              AND c.ts = (
                  SELECT MIN(c2.ts) FROM compras c2
                  WHERE c2.match_id = c.match_id
                    AND c2.item IS NOT NULL AND c2.item <> ''
              )
        ),
        primer_reco AS (
            SELECT r.match_id, r.item AS item
            FROM recomendaciones r
            JOIN partidas_con_win w ON w.match_id = r.match_id
            WHERE r.item IS NOT NULL AND r.item <> ''
              AND r.ts = (
                  SELECT MIN(r2.ts) FROM recomendaciones r2
                  WHERE r2.match_id = r.match_id
                    AND r2.item IS NOT NULL AND r2.item <> ''
              )
        ),
        primer_item AS (
            SELECT w.match_id, w.win,
                   COALESCE(pc.item, pr.item) AS item
            FROM partidas_con_win w
            LEFT JOIN primer_compra pc ON pc.match_id = w.match_id
            LEFT JOIN primer_reco pr ON pr.match_id = w.match_id
        )
        SELECT item,
               COUNT(*) AS partidas,
               SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) AS victorias,
               ROUND(1.0 * SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) / COUNT(*), 4) AS winrate
        FROM primer_item
        WHERE item IS NOT NULL AND item <> ''
        GROUP BY item
        ORDER BY partidas DESC, winrate DESC, item ASC
        """
    )
    return [dict(fila) for fila in cursor.fetchall()]


def resumen_partida(conexion: sqlite3.Connection, match_id: int) -> dict[str, Any]:
    partida = conexion.execute(
        "SELECT * FROM partidas WHERE match_id = ?", (int(match_id),)
    ).fetchone()
    resultado = conexion.execute(
        "SELECT * FROM resultados WHERE match_id = ?", (int(match_id),)
    ).fetchone()
    muestras = conexion.execute(
        "SELECT COUNT(*) AS n, MIN(ts) AS ts_min, MAX(ts) AS ts_max FROM muestras WHERE match_id = ?",
        (int(match_id),),
    ).fetchone()
    recs = conexion.execute(
        "SELECT COUNT(*) AS n FROM recomendaciones WHERE match_id = ?",
        (int(match_id),),
    ).fetchone()
    compras = conexion.execute(
        "SELECT COUNT(*) AS n FROM compras WHERE match_id = ?",
        (int(match_id),),
    ).fetchone()
    videos = conexion.execute(
        "SELECT ruta FROM videos WHERE match_id = ? ORDER BY mtime DESC LIMIT 5",
        (int(match_id),),
    ).fetchall()
    return {
        "match_id": int(match_id),
        "partida": dict(partida) if partida else None,
        "resultado": dict(resultado) if resultado else None,
        "muestras": dict(muestras) if muestras else {"n": 0, "ts_min": None, "ts_max": None},
        "recomendaciones": int(recs["n"]) if recs else 0,
        "compras": int(compras["n"]) if compras else 0,
        "videos": [fila["ruta"] for fila in videos],
    }

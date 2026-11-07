"""Conexión SQLite y migraciones idempotentes."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Raíz del repositorio: <repo>/coach/persistencia/db.py -> <repo>
RAIZ_REPO = Path(__file__).resolve().parents[2]
RUTA_POR_DEFECTO = RAIZ_REPO / "datos" / "coach.db"

MIGRACIONES = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS partidas (
            id INTEGER PRIMARY KEY,
            match_id INTEGER UNIQUE,
            inicio TEXT,
            fin TEXT,
            duracion_s INTEGER,
            heroe TEXT,
            resultado TEXT,
            video TEXT
        );
        CREATE TABLE IF NOT EXISTS muestras (
            id INTEGER PRIMARY KEY,
            match_id INTEGER,
            ts REAL,
            t REAL,
            estado TEXT,
            almas INTEGER,
            oro INTEGER,
            delta REAL,
            recs_json TEXT,
            UNIQUE(match_id, ts)
        );
        CREATE TABLE IF NOT EXISTS compras (
            id INTEGER PRIMARY KEY,
            match_id INTEGER,
            ts REAL,
            cuenta INTEGER,
            heroe TEXT,
            item TEXT,
            item_id TEXT,
            UNIQUE(match_id, ts, cuenta, item_id)
        );
        CREATE TABLE IF NOT EXISTS recomendaciones (
            id INTEGER PRIMARY KEY,
            match_id INTEGER,
            ts REAL,
            item TEXT,
            costo INTEGER,
            alcanzable INTEGER,
            razon TEXT,
            UNIQUE(match_id, ts, item)
        );
        CREATE TABLE IF NOT EXISTS resultados (
            id INTEGER PRIMARY KEY,
            match_id INTEGER UNIQUE,
            win INTEGER,
            duracion_s INTEGER,
            kda TEXT,
            fuente TEXT
        );
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY,
            ruta TEXT UNIQUE,
            bytes INTEGER,
            mtime REAL,
            match_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS agente_log (
            id INTEGER PRIMARY KEY,
            ts REAL,
            pregunta TEXT,
            herramientas TEXT,
            respuesta TEXT,
            tokens INTEGER
        );
        """,
    ),
]


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolver_ruta_db(ruta: str | os.PathLike[str] | None = None) -> Path:
    """Resuelve la ruta de la base de datos.

    Prioridad: argumento explícito, luego ABRAMS_DB, luego <repo>/datos/coach.db.
    """
    if ruta is not None:
        return Path(ruta).expanduser().resolve()
    env = os.environ.get("ABRAMS_DB")
    if env:
        return Path(env).expanduser().resolve()
    return RUTA_POR_DEFECTO


def conectar(ruta: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Abre una conexión sqlite3 con WAL y check_same_thread=False."""
    ruta_db = resolver_ruta_db(ruta)
    ruta_db.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(str(ruta_db), check_same_thread=False)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA journal_mode=WAL")
    conexion.execute("PRAGMA foreign_keys=ON")
    return conexion


def migrar(conexion: sqlite3.Connection) -> list[int]:
    """Aplica migraciones idempotentes y devuelve versiones nuevas aplicadas."""
    conexion.execute(
        """
        CREATE TABLE IF NOT EXISTS migraciones (
            version INTEGER PRIMARY KEY,
            aplicada_en TEXT
        )
        """
    )
    aplicadas = {
        fila[0]
        for fila in conexion.execute("SELECT version FROM migraciones").fetchall()
    }
    nuevas = []
    for version, sql in MIGRACIONES:
        if version in aplicadas:
            continue
        conexion.executescript(sql)
        conexion.execute(
            "INSERT INTO migraciones(version, aplicada_en) VALUES (?, ?)",
            (version, _ahora_iso()),
        )
        nuevas.append(version)
    conexion.commit()
    return nuevas

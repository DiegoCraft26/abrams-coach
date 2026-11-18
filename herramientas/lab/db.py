"""Base de datos del laboratorio: compras ordenadas por partida.

Por qué existe: el motor decide con agregados (cuántas veces se compró un ítem), y eso
no responde las preguntas que sí importan —"¿qué pasa si la primera compra es de 6,400?"
o "¿cuántos 800 caben antes del minuto 10 sin perder?"—. Para responderlas hace falta
el orden real de compras de cada partida, con su tiempo, en una tabla consultable.

Diseño: tres tablas y ninguna lógica de juego.
    partidas  una fila por partida (héroe, resultado, duración, origen)
    compras   una fila por compra, con su orden dentro de la partida
    ensayos   el registro de experimentos: hipótesis, n, efecto, intervalo y veredicto

`ensayos` es lo que impide que el laboratorio se vuelva una colección de anécdotas:
cada hallazgo queda con su tamaño de muestra y su intervalo de confianza. Si el
intervalo cruza cero, el veredicto lo dice.

Uso:
    from herramientas.lab import db
    con = db.conectar()
    db.crear_esquema(con)
"""
from __future__ import annotations

import os
import sqlite3
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUTA = os.path.join(RAIZ, "datos", "lab.db")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS partidas (
    match_id   INTEGER PRIMARY KEY,
    heroe      TEXT NOT NULL,
    gane       INTEGER,              -- 1 / 0 / NULL si no se sabe
    duracion_s INTEGER,
    fuente     TEXT,                 -- replay_cache, deadlock-api, live
    parche     TEXT                  -- corte unix del parche, si se conoce
);

CREATE TABLE IF NOT EXISTS compras (
    match_id INTEGER NOT NULL,
    orden    INTEGER NOT NULL,       -- 1 = primera compra
    t        REAL NOT NULL,          -- segundo de partida
    item_id  TEXT NOT NULL,
    coste    INTEGER,
    vendido_t REAL,
    PRIMARY KEY (match_id, orden)
);

CREATE INDEX IF NOT EXISTS idx_compras_item ON compras (item_id, orden);
CREATE INDEX IF NOT EXISTS idx_compras_t    ON compras (match_id, t);

CREATE TABLE IF NOT EXISTS ensayos (
    id        INTEGER PRIMARY KEY,
    nombre    TEXT UNIQUE NOT NULL,  -- clave estable: repetir actualiza, no duplica
    hipotesis TEXT,
    n         INTEGER,
    efecto    REAL,                  -- en puntos porcentuales
    ic_bajo   REAL,
    ic_alto   REAL,
    veredicto TEXT,
    datos     TEXT,                  -- json con el desglose
    creado    TEXT
);

CREATE TABLE IF NOT EXISTS partidas_api (
    match_id   INTEGER PRIMARY KEY,
    start_time INTEGER,
    duracion_s INTEGER,
    ganador    INTEGER,
    badge      INTEGER,
    parche     TEXT
);

CREATE TABLE IF NOT EXISTS jugadores_api (
    match_id    INTEGER NOT NULL,
    player_slot INTEGER NOT NULL,
    hero_id     INTEGER,
    ganador     INTEGER,
    build_id    INTEGER,
    PRIMARY KEY (match_id, player_slot)
);

CREATE TABLE IF NOT EXISTS compras_api (
    match_id     INTEGER NOT NULL,
    player_slot  INTEGER NOT NULL,
    orden        INTEGER NOT NULL,
    t            REAL NOT NULL,
    item_id      TEXT NOT NULL,
    coste        INTEGER,
    net_worth    INTEGER,
    vendido_t    REAL,
    PRIMARY KEY (match_id, player_slot, orden)
);

CREATE INDEX IF NOT EXISTS idx_api_item ON compras_api (item_id, orden);
"""


def conectar(ruta: str = RUTA) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    return con


def crear_esquema(con: sqlite3.Connection) -> None:
    con.executescript(ESQUEMA)
    con.commit()


def guardar_partida(con, match_id, heroe, gane=None, duracion_s=None,
                    fuente=None, parche=None) -> None:
    con.execute(
        "INSERT INTO partidas (match_id, heroe, gane, duracion_s, fuente, parche) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(match_id) DO UPDATE SET "
        "heroe=excluded.heroe, gane=excluded.gane, duracion_s=excluded.duracion_s, "
        "fuente=excluded.fuente, parche=excluded.parche",
        (int(match_id), heroe, None if gane is None else int(bool(gane)),
         duracion_s, fuente, parche))


def guardar_compras(con, match_id, compras) -> None:
    """`compras` es [(t, item_id, coste, vendido_t)] ya ordenado por tiempo."""
    con.execute("DELETE FROM compras WHERE match_id = ?", (int(match_id),))
    con.executemany(
        "INSERT INTO compras (match_id, orden, t, item_id, coste, vendido_t) "
        "VALUES (?,?,?,?,?,?)",
        [(int(match_id), i + 1, float(t), str(iid), coste, vendido)
         for i, (t, iid, coste, vendido) in enumerate(compras)])


def guardar_ensayo(con, nombre, hipotesis, n, efecto, ic_bajo, ic_alto,
                   veredicto, datos="{}") -> None:
    con.execute(
        "INSERT INTO ensayos (nombre, hipotesis, n, efecto, ic_bajo, ic_alto, "
        "veredicto, datos, creado) VALUES (?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(nombre) DO UPDATE SET hipotesis=excluded.hipotesis, "
        "n=excluded.n, efecto=excluded.efecto, ic_bajo=excluded.ic_bajo, "
        "ic_alto=excluded.ic_alto, veredicto=excluded.veredicto, "
        "datos=excluded.datos, creado=excluded.creado",
        (nombre, hipotesis, int(n), efecto, ic_bajo, ic_alto, veredicto, datos,
         time.strftime("%Y-%m-%dT%H:%M:%S")))


def resumen(con) -> dict:
    f = con.execute("SELECT count(*) FROM partidas").fetchone()[0]
    c = con.execute("SELECT count(*) FROM compras").fetchone()[0]
    e = con.execute("SELECT count(*) FROM ensayos").fetchone()[0]
    h = con.execute("SELECT heroe, count(*) n FROM partidas GROUP BY heroe "
                    "ORDER BY n DESC").fetchall()
    return {"partidas": f, "compras": c, "ensayos": e,
            "heroes": [(r["heroe"], r["n"]) for r in h]}

"""Capa de persistencia SQLite del coach."""

from coach.persistencia.db import conectar, migrar, resolver_ruta_db
from coach.persistencia.repos import (
    guardar_compra,
    guardar_muestra,
    guardar_partida,
    guardar_recomendacion,
    guardar_resultado,
    log_agente,
    resumen_partida,
    ultimas_partidas,
    winrate_por_primer_item,
)

__all__ = [
    "conectar",
    "migrar",
    "resolver_ruta_db",
    "guardar_compra",
    "guardar_muestra",
    "guardar_partida",
    "guardar_recomendacion",
    "guardar_resultado",
    "log_agente",
    "resumen_partida",
    "ultimas_partidas",
    "winrate_por_primer_item",
]

"""Fuentes de datos para el coach: simulado, API en vivo, HUD OCR y compuesto.

Cada fuente implementa la interfaz definida en base.py y devuelve estados
compatibles con Motor.analizar_dict.
"""
from .base import EstadoVacio, FuenteDatos, FuenteError

__all__ = ["EstadoVacio", "FuenteDatos", "FuenteError"]

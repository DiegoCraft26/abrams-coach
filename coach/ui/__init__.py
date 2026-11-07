"""UI nativa del Abrams Coach (GTK4).

Antes todo el panel vivía en `panel_nativo.py` (390 líneas, 960×1080 fijo). Aquí se
separó en componentes con una ventana responsive: `app.py` cablea, `componentes/` dibuja
y `preferencias.py` recuerda tamaño y posición.

La importación de GTK es perezosa a propósito: `coach.ui.preferencias` y
`coach.ui.componentes.base` se pueden usar (y probar) en un entorno sin PyGObject, como el
runner de CI, sin arrastrar la ventana entera.
"""

__all__ = ["App", "Panel", "preferencias"]


def __getattr__(nombre):
    # PEP 562: solo se importa GTK cuando de verdad se pide App o Panel.
    if nombre in ("App", "Panel"):
        from .app import App, Panel
        return {"App": App, "Panel": Panel}[nombre]
    raise AttributeError(f"módulo 'coach.ui' no tiene atributo '{nombre}'")

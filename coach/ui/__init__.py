"""UI nativa del Abrams Coach (GTK4 + libadwaita).

Antes todo el panel vivía en `panel_nativo.py` (390 líneas, 960×1080 fijo). Aquí se
separó en componentes con una ventana responsive: `app.py` cablea, `componentes/` dibuja
y `preferencias.py` recuerda tamaño y posición.
"""
from .app import App, Panel

__all__ = ["App", "Panel"]

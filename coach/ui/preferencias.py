"""Preferencias de ventana: tamaño y posición en ~/.config/abrams-coach/ui.json.

Antes la ventana nacía en 960×1080 y no recordaba nada: cada partida había que moverla
otra vez al monitor secundario.
"""
import json
import os

RUTA = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "abrams-coach", "ui.json")

DEFECTO = {
    "ancho": 960,
    "alto": 1080,
    "maximizado": False,
    "columna": None,      # índice de monitor donde se dejó la ventana
    "breakpoint": "auto",  # auto | angosto | medio | amplio (forzado, para capturas)
}


def cargar(ruta=RUTA):
    """Devuelve las preferencias guardadas, completadas con los valores por defecto."""
    datos = dict(DEFECTO)
    try:
        with open(ruta, encoding="utf-8") as f:
            guardado = json.load(f)
        if isinstance(guardado, dict):
            for k in DEFECTO:
                if k in guardado:
                    datos[k] = guardado[k]
    except (OSError, ValueError):
        pass
    # un archivo corrupto no debe abrir una ventana de 0 px
    datos["ancho"] = max(640, min(1920, int(datos.get("ancho") or 960)))
    datos["alto"] = max(480, min(2160, int(datos.get("alto") or 1080)))
    return datos


def guardar(ancho, alto, maximizado=False, columna=None, breakpoint="auto", ruta=RUTA):
    """Escribe las preferencias; nunca falla (si no se puede, el panel sigue)."""
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ancho": int(ancho), "alto": int(alto),
                       "maximizado": bool(maximizado), "columna": columna,
                       "breakpoint": breakpoint}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, ruta)
        return True
    except OSError:
        return False

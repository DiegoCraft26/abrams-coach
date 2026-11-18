"""Captura de pantalla en Windows. **No probado en Windows**: aquí solo hay Linux.

Por qué existe. La captura de KWin (`captura_kwin.py`) importa `gi` y habla D-Bus con
KWin: en Windows no existe ninguna de las dos. Este módulo es el backend que faltaba,
detrás de la misma interfaz que usa `CapturaCompartida`: una función sin argumentos que
devuelve una imagen PIL en RGB (o `None` si no hay cuadro).

Qué usa, en orden:

1. **`dxcam`** si está instalado: DXGI Desktop Duplication, BGRA rápido, sin borde del
   sistema. Es la opción documentada en `docs/WINDOWS.md`.
2. **`mss`** si está: `BitBlt` por GDI. Más lento, pero funciona en cualquier Windows sin
   privilegios especiales.
3. Si no hay ninguna: `RuntimeError` con el comando exacto para instalar, no un
   `ImportError` a medio camino.

Lo que **no** hace y no puede hacer desde aquí: medir milisegundos por cuadro, comprobar
que respeta el juego en pantalla completa ni que no afecta al rendimiento. Eso necesita
una máquina Windows, y hasta que exista, cualquier cifra de este módulo sería inventada.
"""
from __future__ import annotations

import sys

__all__ = ["backend", "disponible", "motivo"]


def motivo() -> str:
    """Por qué no se puede capturar aquí, en una línea."""
    if not sys.platform.startswith("win"):
        return f"captura de Windows pedida en {sys.platform}"
    try:
        import dxcam  # noqa: F401
        return "dxcam"
    except Exception:                                       # noqa: BLE001
        pass
    try:
        import mss  # noqa: F401
        return "mss"
    except Exception:                                       # noqa: BLE001
        return "sin dxcam ni mss: pip install dxcam (o mss)"


def disponible() -> bool:
    return motivo() in ("dxcam", "mss")


def backend(region=None):
    """Devuelve la función de captura. Lanza RuntimeError si no hay backend real.

    `region` es opcional y por ahora se ignora: en Windows la ventana del juego puede
    estar en cualquier monitor, así que la región se decidirá cuando haya una máquina
    donde medirla. Inventarla aquí sería peor que no tenerla.
    """
    if not sys.platform.startswith("win"):
        raise RuntimeError(f"captura de Windows no disponible: {motivo()}")
    try:
        import dxcam
    except Exception:                                       # noqa: BLE001
        dxcam = None
    if dxcam is not None:
        camara = dxcam.create(output_idx=0)
        if camara is None:
            raise RuntimeError("dxcam no encontró una salida de escritorio")

        def _cuadro_dxcam():
            from PIL import Image
            cuadro = camara.grab()          # BGRA o None si no hay frame nuevo
            if cuadro is None:
                return None
            return Image.fromarray(cuadro[:, :, :3][:, :, ::-1])   # BGR -> RGB

        return _cuadro_dxcam

    try:
        import mss
    except Exception:                                       # noqa: BLE001
        raise RuntimeError(
            "ni dxcam ni mss instalados en Windows: pip install dxcam (recomendado) "
            "o pip install mss") from None
    from PIL import Image

    capturador = mss.mss()

    def _cuadro_mss():
        monitor = capturador.monitors[1]     # el primario
        bruto = capturador.grab(monitor)
        return Image.frombytes("RGB", bruto.size, bruto.bgra, "raw", "BGRX")

    return _cuadro_mss

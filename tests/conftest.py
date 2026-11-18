"""Pytest: raíz del proyecto en sys.path, suites con nombre propio y pantalla virtual.

Las suites están escritas para correr como scripts (`python3 tests/test_x.py`).
Cada módulo expone además `test_suite()` para que `pytest -q` las ejecute igual.

**Pantalla virtual, no la de Diego.** `tests/test_ui.py` corre
`herramientas/capturar_ui.py` en un subproceso, y ese abre el panel real una vez por
tamaño medido (cuatro). El 2026-11-09 eso significó cuatro ventanas encima de su ranked
cada vez que se corría la batería completa. Aquí se levanta un Xvfb propio y se apunta
`DISPLAY` a él antes de que ningún test importe Gtk, así que la batería entera —y sus
subprocesos— pinta fuera de la pantalla real. Si Xvfb no está instalado, no se toca
nada: las suites que no son gráficas siguen corriendo igual.

Para forzar la pantalla de verdad (alguien mirando la UI a propósito): ABRAMS_UI_REAL=1.
"""
import atexit
import os
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

XVFB = os.environ.get("ABRAMS_XVFB") or os.path.expanduser(
    "~/.local/lib/abrams-xvfb/usr/bin/Xvfb")
_xvfb = None


def _display_libre():
    for n in range(90, 121):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}"):
            return n
    return None


def _matar_xvfb():
    global _xvfb
    if _xvfb is not None and _xvfb.poll() is None:
        _xvfb.terminate()
        try:
            _xvfb.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _xvfb.kill()
    _xvfb = None


def _levantar_xvfb():
    """Un X virtual propio para toda la sesión de pytest. Devuelve el DISPLAY o None."""
    global _xvfb
    if os.environ.get("ABRAMS_UI_REAL") == "1":
        return None
    if not (os.path.exists(XVFB) and os.access(XVFB, os.X_OK)):
        return None
    numero = _display_libre()
    if numero is None:
        return None
    try:
        _xvfb = subprocess.Popen(
            [XVFB, f":{numero}", "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        _xvfb = None
        return None
    for _ in range(50):
        if os.path.exists(f"/tmp/.X11-unix/X{numero}"):
            break
        time.sleep(0.1)
    else:
        _matar_xvfb()
        return None
    atexit.register(_matar_xvfb)
    return f":{numero}"


# Los archivos de salida (telemetría, último estado) van a un temporal: si las pruebas
# escriben en `salida/` real, el registro de una partida de verdad queda mezclado con
# datos falsos y ninguna medición sirve después.
import tempfile  # noqa: E402

_SALIDA_PRUEBAS = tempfile.mkdtemp(prefix="abrams-pruebas-")
os.environ.setdefault("ABRAMS_TELEMETRIA",
                      os.path.join(_SALIDA_PRUEBAS, "telemetria.jsonl"))
os.environ.setdefault("ABRAMS_ESTADO",
                      os.path.join(_SALIDA_PRUEBAS, "estado_ultimo.json"))
# El marcador de arranque también: una suite que levanta el servidor en otro puerto
# escribía `salida/version-en-vivo.json` con su propio pid y /api/version acababa
# diciendo «no hay app abierta» con la app abierta (visto el 2026-11-18).
os.environ.setdefault("ABRAMS_VERSION_MARCADOR",
                      os.path.join(_SALIDA_PRUEBAS, "version-en-vivo.json"))
os.environ.setdefault("ABRAMS_CACHE_URL",
                      os.path.join(_SALIDA_PRUEBAS, "urls_broadcast.json"))
os.environ.setdefault("ABRAMS_CUOTA_PAUSA",
                      os.path.join(_SALIDA_PRUEBAS, "cuota_pausa.json"))

_display = _levantar_xvfb()
if _display:
    os.environ["DISPLAY"] = _display
    os.environ.setdefault("GDK_BACKEND", "x11")
    print(f"[conftest] pantalla virtual {_display} (Xvfb): la UI no sale en la real",
          file=sys.stderr)

"""Registro de vida y muerte de los procesos del coach.

El panel se murió alguna vez sin dejar traza: sin excepción, sin mensaje y sin código de
salida, porque el vigilante mandaba su salida a /dev/null y nadie anotaba cómo terminó.
Sin saber si lo mataron o se cayó solo, la causa no se puede encontrar.

`activar("panel")` deja en `/tmp/abrams-panel-crash.log`:

- la línea de arranque (pid, padre, argumentos, hora),
- cualquier excepción no atrapada, incluidas las de hilos,
- el volcado de `faulthandler` si muere por SIGSEGV, SIGABRT, SIGBUS, SIGFPE o SIGILL
  (un aborto de GLib o un fallo del compositor llegan aquí, no a Python),
- la línea de salida con el código o la señal: «matado por SIGKILL» no es lo mismo que
  «código 0» ni que «señal 11».

Además, `kill -USR1 <pid>` vuelca la pila de todos los hilos al mismo archivo sin matar el
proceso: sirve para ver dónde se quedó colgado.
"""
import atexit
import faulthandler
import os
import signal
import sys
import threading
import time
import traceback

_ARCHIVO = None
_ACTIVO_EN = None


def ruta(nombre="panel"):
    return f"/tmp/abrams-{nombre}-crash.log"


def _anotar(texto):
    """Escribe una línea con hora y la vacía al disco en el acto.

    Sin flush, un proceso que muere de golpe se lleva el búfer y la anotación se pierde
    justo cuando hace falta.
    """
    if _ARCHIVO is None:
        return
    try:
        _ARCHIVO.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [pid {os.getpid()}] {texto}\n")
        _ARCHIVO.flush()
    except (OSError, ValueError):
        pass


def _manejador_senal(numero, _marco):
    """Anota la señal y se comporta como si no la hubiéramos atrapado.

    Se repone el manejador por defecto y se relanza para que el proceso termine como
    debía: el objetivo es dejar constancia, no cambiar el comportamiento.
    """
    try:
        nombre = signal.Signals(numero).name
    except ValueError:
        nombre = f"señal {numero}"
    _anotar(f"señal {nombre} recibida")
    try:
        signal.signal(numero, signal.SIG_DFL)
        os.kill(os.getpid(), numero)
    except (OSError, ValueError):
        os._exit(1)


def _excepcion(tipo, valor, tb):
    _anotar("excepción no atrapada:\n" + "".join(
        traceback.format_exception(tipo, valor, tb)).rstrip())


def _excepcion_hilo(args):
    if args.exc_type is SystemExit:
        return
    _anotar(f"excepción en el hilo {getattr(args.thread, 'name', '?')}:\n" + "".join(
        traceback.format_exception(args.exc_type, args.exc_value,
                                   args.exc_traceback)).rstrip())


def _salida():
    _anotar("salida limpia (atexit)")


def activar(nombre="panel", archivo=None):
    """Deja el registro de muerte puesto. Se puede llamar dos veces sin daño.

    Devuelve la ruta del archivo, para poder enseñarla en el diagnóstico.
    """
    global _ARCHIVO, _ACTIVO_EN
    if _ACTIVO_EN == nombre:
        return ruta(nombre)
    destino = archivo or ruta(nombre)
    try:
        _ARCHIVO = open(destino, "a", encoding="utf-8")
    except OSError:
        return None
    _ACTIVO_EN = nombre

    # faulthandler cubre SIGSEGV, SIGABRT, SIGBUS, SIGFPE y SIGILL, y escribe fuera de
    # Python: es lo único que deja traza cuando el fallo es de GTK o del compositor.
    faulthandler.enable(file=_ARCHIVO, all_threads=True)
    try:
        faulthandler.register(signal.SIGUSR1, file=_ARCHIVO, all_threads=True,
                              chain=False)
    except (AttributeError, ValueError, OSError):
        pass

    sys.excepthook = _excepcion
    threading.excepthook = _excepcion_hilo
    atexit.register(_salida)
    for numero in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(numero, _manejador_senal)
        except (ValueError, OSError):
            pass

    _anotar(f"arranque {nombre}: padre {os.getppid()} · {sys.executable} "
            f"{' '.join(sys.argv[1:])}")
    return destino


def rss_mb():
    """Memoria residente en MB, leída de /proc. Sirve para descartar una fuga."""
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for linea in f:
                if linea.startswith("VmRSS:"):
                    return round(int(linea.split()[1]) / 1024, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None

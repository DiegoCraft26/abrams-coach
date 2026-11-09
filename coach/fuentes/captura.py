"""Captura compartida del escritorio, de alta frecuencia.

Por qué existe: capturar la pantalla cuesta, y si cada lector captura por su cuenta el
ciclo se multiplica. Aquí hay **un** hilo capturando y todos los lectores miran el último
cuadro.

Medido en la máquina de desarrollo, escritorio 4480×1440:
    `spectacle -f` (método viejo) .... 415 ms + 71 ms de abrir el PNG
    KWin CaptureWorkspace ............ 34 ms en frío, 38 ms de mediana ya en el ciclo
    tesseract (recorte) .............. 94 ms

Con KWin el ciclo baja de ~490 ms a ~40 ms. El intervalo por defecto es 0.5 s (2 Hz):
el reloj del HUD cambia una vez por segundo y el marcador se lee del último cuadro, así
que capturar a 5.5 Hz solo gastaba GPU en recomponer cuadros. Si KWin no contesta en
300 ms, se cae a `spectacle` como antes.

El hilo no se enciende solo: lo enciende `coach.nucleo_vivo.hilo_hud` cuando hay juego
abierto y lo para cuando no, que es cuando no hay nada que leer.
"""
import os
import statistics
import subprocess
import tempfile
import threading
import time

from PIL import Image

from . import captura_kwin

RUTA_CUADRO = os.path.join(tempfile.gettempdir(), "abrams-cuadro.png")
ESPECTACLE = ["spectacle", "-b", "-n", "-f", "-o"]


class CapturaCompartida:
    """Un hilo que captura sin parar y publica el último cuadro con su hora."""

    def __init__(self, ruta=RUTA_CUADRO, intervalo=0.5, comando=None):
        self.ruta = ruta
        self.intervalo = intervalo
        self.comando = comando      # None = KWin; una lista = ese comando y su archivo
        self.lock = threading.Lock()
        self.cuadro = None          # PIL.Image del último cuadro válido
        self.ts = 0.0               # cuándo se terminó de capturar
        self.capturas = 0
        self.fallos = 0
        self.ms = []                # últimas 40 duraciones de captura
        self._parar = threading.Event()
        self._hilo = None
        self.ultimo_error = None

    # ------------------------------------------------------------------
    def arrancar(self):
        if self._hilo and self._hilo.is_alive():
            return self
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()
        return self

    def parar(self):
        self._parar.set()

    def _cuadro(self):
        """Un cuadro del escritorio: por KWin (~35 ms) o con el comando de siempre."""
        if self.comando is None:
            im = captura_kwin.capturar_escritorio()
            if im is not None:
                return im.convert("RGB")
        subprocess.run((self.comando or ESPECTACLE) + [self.ruta], check=True, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cuadro = Image.open(self.ruta)
        cuadro.load()
        return cuadro

    def _bucle(self):
        while not self._parar.is_set():
            t0 = time.perf_counter()
            try:
                cuadro = self._cuadro()
                dur = (time.perf_counter() - t0) * 1000
                with self.lock:
                    self.cuadro = cuadro
                    self.ts = time.time()
                    self.capturas += 1
                    self.ms = (self.ms + [dur])[-40:]
                del cuadro
            except Exception as exc:                            # noqa: BLE001
                self.ultimo_error = f"{type(exc).__name__}: {exc}"
                with self.lock:
                    self.fallos += 1
                time.sleep(min(2.0, self.intervalo + 0.2))
            time.sleep(self.intervalo)

    # ------------------------------------------------------------------
    def ultimo(self, max_edad_s=2.0):
        """(cuadro, edad_en_segundos) o (None, None) si no hay nada fresco."""
        with self.lock:
            if self.cuadro is None:
                return None, None
            edad = time.time() - self.ts
            if max_edad_s is not None and edad > max_edad_s:
                return None, edad
            return self.cuadro, edad

    def metricas(self):
        with self.lock:
            ms = list(self.ms)
            return {
                "capturas": self.capturas,
                "fallos": self.fallos,
                "ms_mediana": round(statistics.median(ms), 1) if ms else None,
                "ms_p95": round(sorted(ms)[int(len(ms) * 0.95)], 1) if len(ms) >= 4 else None,
                "edad_s": round(time.time() - self.ts, 2) if self.ts else None,
                "error": self.ultimo_error,
            }


_INSTANCIA = None
_LOCK = threading.Lock()


def global_():
    """Instancia única por proceso (la captura es cara como para tener varias)."""
    global _INSTANCIA
    with _LOCK:
        if _INSTANCIA is None:
            _INSTANCIA = CapturaCompartida().arrancar()
        return _INSTANCIA


def parar_global():
    global _INSTANCIA
    with _LOCK:
        if _INSTANCIA is not None:
            _INSTANCIA.parar()
            _INSTANCIA = None


def metricas_si_arriba():
    """Métricas de la captura si ya está arriba; {} si no. No la arranca.

    Pedir métricas para el panel no puede encender un hilo que captura el escritorio
    entero: eso costaba ~10 % de un núcleo solo por rellenar un número.
    """
    inst = _INSTANCIA
    return inst.metricas() if inst is not None else {}

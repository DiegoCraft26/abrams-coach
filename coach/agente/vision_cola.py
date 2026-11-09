"""Cola de visión: un cuadro a la vez, prioridad para lo que importa.

Lo medido el 2026-11-09 con la API real manda el diseño:

- una lectura de 640 px tarda ~23 s, no 8. Pedir 1 cuadro cada 5 s no se puede cumplir
  esperando la respuesta, así que la cola **nunca tiene más de una petición en vuelo**;
  lo que llega mientras tanto se encola y se descarta si el cuadro es el mismo.
- la tienda abierta y el marcador valen más que el reloj, así que van con prioridad y
  adelantan a los cuadros periódicos.
- el panel no espera a nadie: pide `ultimo()` y pinta lo que haya con su edad.
- si la cuota de la partida se agota, la cola lo dice en vez de seguir intentando.
"""
from __future__ import annotations

import queue
import threading
import time

from . import vision

PRIORIDAD = {
    "tienda": 0,
    "marcador": 0,
    "muerte": 1,
    "periodico": 2,
}

# El intervalo no es el ritmo de envío sino el mínimo entre dos arranques: con 23 s de
# respuesta, es lo que evita tener tres peticiones peleándose por la misma cuota.
INTERVALO_S = 5.0


class ColaVision:
    """Un hilo, una petición en vuelo y el último estado con su edad."""

    def __init__(self, proveedor=None, intervalo_s: float = INTERVALO_S,
                 tope: "vision.TopePartida | None" = None, timeout_s: float | None = None):
        self.proveedor = proveedor
        self.intervalo_s = float(intervalo_s)
        self.tope = tope or vision.TOPE
        self.timeout_s = timeout_s or vision.TIMEOUT_S
        self._cola: "queue.PriorityQueue" = queue.PriorityQueue()
        self._lock = threading.Lock()
        self._secuencia = 0
        self._ultimo: dict | None = None
        self._ts_ultimo = 0.0
        self._ultimo_arranque = 0.0
        self._en_curso: str | None = None
        self._hashes_vistos: set[str] = set()
        self._encolados = 0
        self._descartados = 0
        self._fallos = 0
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._agotado = False

    # ------------------------------------------------------------ ciclo
    def arrancar(self):
        if self._hilo and self._hilo.is_alive():
            return self
        self._parar.clear()
        self._hilo = threading.Thread(target=self._trabajar, name="vision",
                                     daemon=True)
        self._hilo.start()
        return self

    def parar(self, espera: float = 2.0):
        self._parar.set()
        # Despierta al hilo aunque esté esperando en la cola.
        self._cola.put((99, self._siguiente(), ("__fin__", None, "")))
        if self._hilo:
            self._hilo.join(timeout=espera)

    def _siguiente(self) -> int:
        with self._lock:
            self._secuencia += 1
            return self._secuencia

    # ------------------------------------------------------------ entrada
    def encolar(self, cuadro, motivo: str = "periodico", caja=None) -> bool:
        """Mete un cuadro si vale la pena. Devuelve False si se descartó.

        Se descarta cuando: la partida ya gastó su tope, el cuadro está en la cola o en
        vuelo (mismo hash) o llega otro igual mientras se procesa.
        """
        if self._agotado or not self.tope.puede():
            self._agotado = True
            return False
        try:
            recorte = vision.recorte_juego(cuadro, caja)
            jpeg = vision.cuadro_a_jpeg(recorte)
        except Exception:                                 # noqa: BLE001
            self._fallos += 1
            return False
        clave = vision.hash_cuadro(jpeg)
        with self._lock:
            if clave in self._hashes_vistos:
                self._descartados += 1
                return False
            self._hashes_vistos.add(clave)
            if len(self._hashes_vistos) > 600:
                self._hashes_vistos.clear()
                self._hashes_vistos.add(clave)
            self._encolados += 1
        prioridad = PRIORIDAD.get(motivo, 2)
        self._cola.put((prioridad, self._siguiente(), (clave, jpeg, motivo)))
        return True

    # ------------------------------------------------------------ salida
    def ultimo(self) -> dict:
        """Lo último leído, con la edad. `estado` es None si nunca hubo lectura."""
        with self._lock:
            edad = (time.time() - self._ts_ultimo) if self._ts_ultimo else None
            return {
                "estado": self._ultimo,
                "edad_s": round(edad, 1) if edad is not None else None,
                "en_curso": self._en_curso,
                "encolados": self._encolados,
                "descartados": self._descartados,
                "fallos": self._fallos,
                "agotado": self._agotado,
                "tope": self.tope.estado(),
            }

    # ------------------------------------------------------------ trabajo
    def _trabajar(self):
        while not self._parar.is_set():
            # El intervalo se cumple aquí, no al encolar: el que encola no espera nunca.
            falta = self.intervalo_s - (time.time() - self._ultimo_arranque)
            if falta > 0:
                self._parar.wait(min(falta, 0.25))
                continue
            try:
                prioridad, _, (clave, jpeg, motivo) = self._cola.get(timeout=0.5)
            except queue.Empty:
                continue
            if clave == "__fin__":
                return
            if not self.tope.puede():
                self._agotado = True
                continue
            with self._lock:
                self._en_curso = motivo
            self._ultimo_arranque = time.time()
            try:
                estado = vision.interpretar(jpeg, proveedor=self.proveedor,
                                            timeout_s=self.timeout_s,
                                            tope=self.tope, usar_cache=False)
            except Exception:                             # noqa: BLE001
                estado = None
            finally:
                with self._lock:
                    self._en_curso = None
            if estado is None:
                with self._lock:
                    self._fallos += 1
                continue
            estado["_motivo"] = motivo
            with self._lock:
                self._ultimo = estado
                self._ts_ultimo = time.time()


_COLA_GLOBAL: ColaVision | None = None
_LOCK_GLOBAL = threading.Lock()


def cola(proveedor=None, **kwargs) -> ColaVision:
    """La cola del proceso: una sola para no pelearse por la cuota."""
    global _COLA_GLOBAL
    with _LOCK_GLOBAL:
        if _COLA_GLOBAL is None:
            _COLA_GLOBAL = ColaVision(proveedor=proveedor, **kwargs)
        return _COLA_GLOBAL


def estado() -> dict:
    """Para /api/revisar: sin imágenes, sin claves."""
    with _LOCK_GLOBAL:
        if _COLA_GLOBAL is None:
            return {"iniciada": False}
        return dict(_COLA_GLOBAL.ultimo(), iniciada=True)

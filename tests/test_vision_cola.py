"""La cola de visión: una petición en vuelo, prioridad y el panel sin esperar.

Con la latencia medida (~23 s por cuadro) lo que hay que probar no es la velocidad sino
que la cola no se atropelle: nada de dos peticiones a la vez, los cuadros repetidos no se
pagan, la tienda adelanta al reloj y el panel siempre puede leer algo con su edad.
"""
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from coach.agente import vision, vision_cola  # noqa: E402


class ProveedorLento:
    """Cuenta llamadas y tarda lo que se le diga, como la API de verdad."""

    def __init__(self, retraso=0.0, fallar=False):
        self.retraso = retraso
        self.fallar = fallar
        self.llamadas = 0
        self.concurrentes = 0
        self.max_concurrentes = 0

    def hay_clave(self):
        return True

    def chat_vision(self, imagen, texto, sistema=None, timeout_s=8.0):
        self.llamadas += 1
        self.concurrentes += 1
        self.max_concurrentes = max(self.max_concurrentes, self.concurrentes)
        try:
            if self.retraso:
                time.sleep(self.retraso)
            if self.fallar:
                raise RuntimeError("API caída")
            return {"choices": [{"message": {"content":
                                             '{"fase": "en_partida", "reloj_s": 300}'}}],
                    "usage": {"total_tokens": 100}}
        finally:
            self.concurrentes -= 1


def _cuadro(tono):
    from PIL import Image

    return Image.new("RGB", (600, 360), (tono, 30, 30))


def _esperar(condicion, tope_s=4.0):
    inicio = time.time()
    while time.time() - inicio < tope_s:
        if condicion():
            return True
        time.sleep(0.02)
    return False


def test_una_sola_peticion_en_vuelo():
    vision._CACHE.clear()
    falso = ProveedorLento(retraso=0.3)
    cola = vision_cola.ColaVision(proveedor=falso, intervalo_s=0.01,
                                  tope=vision.TopePartida(tope=50)).arrancar()
    try:
        for tono in (10, 20, 30, 40, 50):
            cola.encolar(_cuadro(tono), "periodico")
        assert _esperar(lambda: cola.ultimo()["estado"] is not None, 6.0)
        assert falso.max_concurrentes == 1, "dos peticiones a la vez"
    finally:
        cola.parar()


def test_el_mismo_cuadro_no_se_encola_dos_veces():
    vision._CACHE.clear()
    falso = ProveedorLento()
    cola = vision_cola.ColaVision(proveedor=falso, intervalo_s=0.01).arrancar()
    try:
        cuadro = _cuadro(77)
        assert cola.encolar(cuadro) is True
        assert cola.encolar(cuadro) is False     # mismo hash
    finally:
        cola.parar()


def test_el_ultimo_trae_el_estado_con_su_edad():
    vision._CACHE.clear()
    falso = ProveedorLento()
    cola = vision_cola.ColaVision(proveedor=falso, intervalo_s=0.01).arrancar()
    try:
        cola.encolar(_cuadro(88))
        assert _esperar(lambda: cola.ultimo()["estado"] is not None)
        ultimo = cola.ultimo()
        assert ultimo["estado"]["fase"] == "en_partida"
        assert ultimo["edad_s"] is not None and ultimo["edad_s"] >= 0
        assert ultimo["en_curso"] is None
        assert ultimo["estado"]["_motivo"] == "periodico"
    finally:
        cola.parar()


def test_la_tienda_adelanta_al_reloj():
    """Con dos cuadros esperando, sale primero el de la tienda."""
    vision._CACHE.clear()
    puerta = threading.Event()

    class Bloqueante(ProveedorLento):
        """La primera llamada se queda esperando para que haya cola de verdad."""

        def chat_vision(self, imagen, texto, sistema=None, timeout_s=8.0):
            if not puerta.is_set():
                puerta.wait(3.0)
            return super().chat_vision(imagen, texto, sistema, timeout_s)

    falso = Bloqueante(retraso=0.25)   # para que el sondeo alcance a ver cada uno
    cola = vision_cola.ColaVision(proveedor=falso, intervalo_s=0.01).arrancar()
    try:
        cola.encolar(_cuadro(11), "periodico")          # ocupa al trabajador
        assert _esperar(lambda: cola.ultimo()["en_curso"] is not None, 3.0)
        cola.encolar(_cuadro(22), "periodico")
        cola.encolar(_cuadro(33), "tienda")
        puerta.set()
        vistos = []
        objeto_previo = None
        inicio = time.time()
        while time.time() - inicio < 6.0 and len(vistos) < 3:
            estado = cola.ultimo()["estado"]
            if estado is not None and estado is not objeto_previo:
                objeto_previo = estado
                vistos.append(estado["_motivo"])
            time.sleep(0.02)
        # El que estaba en vuelo, luego la tienda, luego el periódico que esperaba.
        assert vistos[1] == "tienda", vistos
        assert vistos[-1] == "periodico", vistos
    finally:
        cola.parar()


def test_si_un_cuadro_falla_la_cola_sigue():
    vision._CACHE.clear()
    falso = ProveedorLento(fallar=True)
    cola = vision_cola.ColaVision(proveedor=falso, intervalo_s=0.01).arrancar()
    try:
        cola.encolar(_cuadro(33))
        assert _esperar(lambda: cola.ultimo()["fallos"] >= 1, 4.0)
        assert cola.ultimo()["estado"] is None
        assert cola.ultimo()["en_curso"] is None
    finally:
        cola.parar()


def test_al_agotar_el_tope_deja_de_encolar():
    vision._CACHE.clear()
    falso = ProveedorLento()
    cola = vision_cola.ColaVision(proveedor=falso, intervalo_s=0.01,
                                  tope=vision.TopePartida(tope=1)).arrancar()
    try:
        assert cola.encolar(_cuadro(44)) is True
        assert _esperar(lambda: cola.ultimo()["estado"] is not None)
        assert _esperar(lambda: cola.ultimo()["agotado"] or
                        cola.encolar(_cuadro(55)) is False, 3.0)
        assert cola.encolar(_cuadro(66)) is False
    finally:
        cola.parar()


def test_la_prioridad_esta_declarada_para_los_motivos_conocidos():
    for motivo in ("tienda", "marcador", "muerte", "periodico"):
        assert motivo in vision_cola.PRIORIDAD
    assert vision_cola.PRIORIDAD["tienda"] < vision_cola.PRIORIDAD["periodico"]

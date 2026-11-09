"""Captura bajo demanda: qué cuadro se manda, de dónde y con qué prioridad.

La visión cuesta ~23 s y ~3 600 tokens por cuadro: aquí se decide cuándo vale la pena
gastarlo. Y se recorta el monitor del juego, no el escritorio entero.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from coach.fuentes import captura_bajo_demanda as cbd  # noqa: E402

SALIDA_KSCREEN = """
Output: 1 HDMI-A-1 2f541efa-80da-47d2-b27d-138ce41b7b6e
\t enabled
\t connected
\t priority 2
\t Geometry: 0,360 1920x1080
Output: 2 DP-2 14fec8ce-724f-4fe5-88cf-81cdd3aee7d7
\t enabled
\t connected
\t priority 1
\t Geometry: 1920,0 2560x1440
"""


def test_parsea_los_monitores_de_kscreen():
    salidas = cbd._parsear_salidas(SALIDA_KSCREEN)
    assert len(salidas) == 2
    assert salidas[0][:5] == ("HDMI-A-1", 0, 360, 1920, 1080)
    assert salidas[1][5] == 1          # prioridad del principal


def test_elige_el_monitor_principal(monkeypatch):
    monkeypatch.setattr(cbd, "salidas", lambda: cbd._parsear_salidas(SALIDA_KSCREEN))
    monkeypatch.setattr(cbd, "_CACHE_CAJA", {"ts": 0.0, "caja": None})
    assert cbd.caja_juego(forzar=True) == (1920, 0, 2560, 1440)


def test_sin_monitores_devuelve_none(monkeypatch):
    monkeypatch.setattr(cbd, "salidas", lambda: [])
    monkeypatch.setattr(cbd, "_CACHE_CAJA", {"ts": 0.0, "caja": None})
    assert cbd.caja_juego(forzar=True) is None


class ColaFalsa:
    def __init__(self, acepta=True):
        self.acepta = acepta
        self.pedidos = []

    def encolar(self, cuadro, motivo="periodico", caja=None):
        self.pedidos.append((motivo, caja))
        return self.acepta


def _scheduler(cola, ahora=None):
    reloj = {"t": 1000.0 if ahora is None else ahora}
    sched = cbd.SchedulerVision(cola, intervalo_s=20.0,
                               capturador=lambda: "cuadro",
                               caja_fn=lambda: (1920, 0, 2560, 1440))
    return sched, reloj


def test_manda_el_primer_cuadro_y_luego_respeta_el_intervalo(monkeypatch):
    cola = ColaFalsa()
    sched, _ = _scheduler(cola)
    assert sched.quizas_encolar("periodico") is True
    assert sched.quizas_encolar("periodico") is False   # antes de 20 s
    assert len(cola.pedidos) == 1


def test_el_ritmo_global_no_se_puede_saltar():
    """Un cuadro cada `intervalo_s` como mucho, venga del motivo que venga."""
    cola = ColaFalsa()
    sched, _ = _scheduler(cola)
    assert sched.quizas_encolar("tienda") is True
    assert sched.quizas_encolar("periodico") is False


def test_la_tienda_vuelve_antes_que_el_periodico():
    """La tienda tiene un mínimo más corto: es donde está el inventario."""
    cola = ColaFalsa()
    sched, _ = _scheduler(cola)
    assert sched.quizas_encolar("tienda") is True
    # Han pasado 7 s: por debajo del ritmo global (20 s) y por encima del de tienda
    # (~6.7 s). Solo la tienda puede volver a entrar.
    sched._ultimo_tienda -= 7.0
    assert sched.quizas_encolar("periodico") is False
    assert sched.quizas_encolar("tienda") is True


def test_no_encola_si_no_hay_cuadro():
    cola = ColaFalsa()
    sched = cbd.SchedulerVision(cola, intervalo_s=0.0, capturador=lambda: None,
                                caja_fn=lambda: None)
    assert sched.quizas_encolar("periodico") is False
    assert cola.pedidos == []
    assert sched.descartes == 1


def test_si_la_cola_rechaza_se_cuenta_como_descarte():
    sched = cbd.SchedulerVision(ColaFalsa(acepta=False), intervalo_s=0.0,
                                capturador=lambda: "cuadro", caja_fn=lambda: None)
    assert sched.quizas_encolar("periodico") is False
    assert sched.descartes == 1
    assert sched.enviados == 0


def test_el_motivo_sale_de_lo_ultimo_leido():
    assert cbd.motivo_por_estado(None) == "periodico"
    assert cbd.motivo_por_estado({"tienda_abierta": True}) == "tienda"
    assert cbd.motivo_por_estado({"marcador_abierto": True}) == "marcador"
    assert cbd.motivo_por_estado({"fase": "en_partida"}) == "periodico"


def test_cada_tantas_lecturas_mira_la_tienda():
    """Con una lectura periódica cada 25 s, una mirada a la tienda cada 4."""
    from PIL import Image

    cuadro = Image.new("RGB", (2560, 1440), (30, 40, 50))
    cola = ColaFalsa()
    sched = cbd.SchedulerVision(cola, intervalo_s=0.0, capturador=lambda: cuadro,
                                caja_fn=lambda: (0, 0, 2560, 1440), cada_tienda=2)
    motivos = []
    for _ in range(4):
        sched.quizas_encolar("periodico")
        motivos.append(cola.pedidos[-1][0])
    assert motivos == ["periodico", "tienda", "periodico", "tienda"]


def test_la_cadencia_de_tienda_se_adapta():
    """Abierta se mira seguido; cerrada, poco. Así no se gasta en balde."""
    sched = cbd.SchedulerVision(None, intervalo_s=25.0)
    sched.ajustar_tienda(True)
    assert sched.cada_tienda == 2
    sched.ajustar_tienda(False)
    assert sched.cada_tienda == 8

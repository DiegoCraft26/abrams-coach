"""El OCR remoto es opcional y su ausencia nunca puede tumbar el panel.

Contexto medido el 2026-11-15 en la PC de 4 hilos (i5-2500): una lectura de HUD por
tesseract tarda **1.1-1.8 s** contra **155 ms** en la máquina que juega. La causa no es
tesseract (0.10 s en las dos), sino el `fork` de un proceso Python que ya tiene numpy
cargado. Por eso `hud_remoto` no está cableado en el bucle: existe como experimento y
estas pruebas solo garantizan que falla en silencio, devolviendo None.
"""
import socket

from PIL import Image

from coach.fuentes import hud_rapido, hud_remoto


def test_sin_servidor_no_intenta_nada():
    assert hud_remoto.leer("", None) is None


def test_servidor_caido_devuelve_none_sin_lanzar():
    """Un puerto cerrado es lo normal si la PC está apagada: no puede haber excepción."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    marco = hud_rapido.MarcoPerezoso(
        capturador=lambda caja: Image.new("RGB", (8, 8)), tamano=(4480, 1440))
    met = {}
    salida = hud_remoto.leer(f"http://127.0.0.1:{puerto}", marco, timeout_s=0.4,
                             metricas=met)
    assert salida is None
    assert met.get("fallos") == 1


def test_el_marco_perezoso_sigue_siendo_el_local():
    """El mismo objeto sirve para el OCR local y para el remoto: una sola captura."""
    vistas = []

    def capturar(caja):
        vistas.append(tuple(caja))
        return Image.new("RGB", (int(caja[2] - caja[0]), int(caja[3] - caja[1])))

    marco = hud_rapido.MarcoPerezoso(capturador=capturar, tamano=(4480, 1440))
    assert marco.size == (4480, 1440)
    marco.crop((10, 10, 60, 60))
    assert vistas == [(10, 10, 60, 60)]

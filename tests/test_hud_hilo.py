"""El hilo del HUD tiene que arrancar en un proceso vivo, no morir al importar.

Regresión del 2026-11-09: `hilo_hud` importaba `lector`, un módulo que ya no existía.
El hilo moría con ImportError antes de leer nada, el reloj del HUD nunca se publicaba y
el panel decía «sin partida activa» durante una ranked de verdad. La suite no lo vio
porque nadie arrancaba el hilo.
"""
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from coach import nucleo_vivo  # noqa: E402


def test_los_modulos_que_necesita_el_hilo_existen():
    # Los mismos nombres que importa `hilo_hud`, comprobados uno a uno.
    from coach.fuentes import captura, captura_kwin, hud_rapido
    assert callable(captura.global_)
    assert callable(captura_kwin.capturar_escritorio)
    assert callable(hud_rapido.leer)


def test_el_hilo_sobrevive_a_un_juego_cerrado(monkeypatch):
    estado = {"t": None, "oro": None, "ts": 0.0}
    # Sin juego abierto el hilo solo duerme: si el import fallara, el hilo moriría y
    # `is_alive()` sería False.
    monkeypatch.setattr(nucleo_vivo, "juego_abierto", lambda: False)
    hilo = threading.Thread(target=nucleo_vivo.hilo_hud, args=(estado, {}), daemon=True)
    hilo.start()
    time.sleep(0.6)
    assert hilo.is_alive()

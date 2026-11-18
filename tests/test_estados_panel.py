"""Los estados terminales del panel: congelado, fuera de partida y cierre del juego.

Son los que se ven justo cuando algo va mal, y los que más fácil se rompen en silencio.
El caso real que originó estas pruebas (2026-11-15): el panel decía «sin partida» cuando
se congelaba el stream, y seguía diciendo «en partida» con el juego ya cerrado.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import pytest  # noqa: E402

from coach import nucleo_vivo as NV            # noqa: E402
from coach.fuentes import log_juego            # noqa: E402


@pytest.fixture()
def publicado(monkeypatch):
    caja = {}

    def falso(datos):
        caja.clear()
        caja.update(datos)

    monkeypatch.setattr(NV.servidor.EST, "publicar", falso)
    return caja


def test_congelado_conserva_la_foto_y_la_marca_rancia(publicado, monkeypatch):
    """Si el stream se para no se borra lo que había: se marca con su edad."""
    monkeypatch.setattr(NV.servidor.EST, "leer",
                        lambda: ({"t": 1810, "almas": 24000, "fuente": "en_vivo"}, 7))
    NV.publicar_congelado(tick=42)
    assert publicado["t"] == 1810 and publicado["almas"] == 24000
    assert publicado["rancio"] is True
    assert publicado["listo"] is True, "antes ponía listo=False y parecía desconectado"
    assert "42" in publicado["mensaje"]


def test_congelado_sin_nada_previo_no_revienta(publicado, monkeypatch):
    monkeypatch.setattr(NV.servidor.EST, "leer", lambda: (None, 0))
    NV.publicar_congelado(tick=None)
    assert publicado["rancio"] is True and publicado["listo"] is True


def test_fuera_de_partida_dice_el_reloj_y_quien_eres(publicado):
    NV.publicar_fuera_de_partida({"t": 725}, cuenta=123456)
    assert "12:05" in publicado["mensaje"]
    assert "123456" in publicado["mensaje"]
    assert publicado["listo"] is False


def test_fuera_de_partida_sin_cuenta_pide_el_dato(publicado):
    NV.publicar_fuera_de_partida({"t": 60}, cuenta=None)
    assert "--cuenta" in publicado["mensaje"] or "--mi-heroe" in publicado["mensaje"]


def test_el_juego_cerrado_no_es_partida(monkeypatch, tmp_path):
    ruta = tmp_path / "console.log"
    ruta.write_text("[HostStateManager] Host activate: Loading (dl_midtown)\n"
                    "[Client] ChangeGameState: GameInProgress (7)\n"
                    "Source2Shutdown\n", encoding="utf-8")
    monkeypatch.setattr(log_juego, "RUTA", str(ruta))
    log_juego._cache.update({"mtime": None, "size": None, "pos": 0, "fase": None,
                             "mapa": None, "cerrado": False})
    assert log_juego.en_partida() is False
    assert log_juego.estado_ui()[0] is None


def test_la_apertura_publica_de_donde_sale(publicado):
    conoc = {"465043967": {"nombre": "Spirit Strike", "costo": 800, "n": 10},
             "1342610602": {"nombre": "Close Quarters", "costo": 800, "n": 10}}
    assert NV.publicar_apertura(conoc) is True
    assert publicado["fuente_apertura"]
    assert publicado["plan"]

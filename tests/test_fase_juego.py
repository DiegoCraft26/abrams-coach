"""Fase del juego desde el console.log y captura por caja.

Dos defectos reales que vigilan estas pruebas (2026-11-15):

1. El panel decía «veo el marcador y las 12 almas, pero no sé cuál eres tú» abriendo la
   app en el menú, sin partida y sin haber leído un solo número. La fase ahora se sabe
   gratis por el `console.log` del juego y el menú no se presenta como error.
2. El hilo del HUD pedía el escritorio entero (4480×1440, ~64 ms) cada 2 s para recortar
   dos cajas de 100×40. Ese readback completo es el tirón que se nota en peleas.
"""
import os
import time

import pytest

from coach.fuentes import hud_rapido, log_juego


@pytest.fixture()
def log_sintetico(tmp_path, monkeypatch):
    """Un console.log falso con la fase y el mapa que se quieran, y su antigüedad."""
    ruta = tmp_path / "console.log"

    def escribir(fase, edad_s=0.0, mapa="dl_midtown", hideout=False, cerrar=False):
        lineas = [
            f"[HostStateManager] Host activate: Loading ({'dl_hideout' if hideout else mapa})",
            "[Client] ChangeGameState: WaitingForPlayersToJoin (2)",
            f"[Client] ChangeGameState: {fase} (7)",
        ]
        if cerrar:
            lineas.append("Source2Shutdown")
        ruta.write_text("\n".join(l for l in lineas if l) + "\n", encoding="utf-8")
        if edad_s:
            viejo = time.time() - edad_s
            os.utime(ruta, (viejo, viejo))
        return str(ruta)

    monkeypatch.setattr(log_juego, "RUTA", str(ruta))
    log_juego._cache.update({"mtime": None, "size": None, "pos": 0, "fase": None,
                             "mapa": None, "cerrado": False})
    return escribir


def test_en_partida_cuando_el_log_dice_gameinprogress(log_sintetico):
    log_sintetico("GameInProgress")
    log_juego.actualizar(force=True)
    fase, frescura = log_juego.estado_ui()
    assert fase == "partida"
    assert frescura is not None and frescura < 5


def test_el_hideout_es_menu_aunque_diga_gameinprogress(log_sintetico):
    """El menú (hideout) también pasa por HeroSelection y GameInProgress.

    El 2026-11-15 el panel afirmaba «en partida» con Diego en el menú. La señal que
    separa de verdad es el mapa cargado, no la fase del motor.
    """
    log_sintetico("GameInProgress", hideout=True)
    log_juego.actualizar(force=True)
    assert log_juego.mapa() == "dl_hideout"
    assert log_juego.en_menu() is True
    assert log_juego.en_partida() is False
    fase, _ = log_juego.estado_ui()
    assert fase == "menu"


def test_un_mapa_de_verdad_si_es_partida(log_sintetico):
    log_sintetico("GameInProgress", mapa="dl_midtown")
    log_juego.actualizar(force=True)
    assert log_juego.en_menu() is False
    assert log_juego.estado_ui()[0] == "partida"


def test_el_cierre_del_juego_apaga_el_estado(log_sintetico):
    """`Source2Shutdown` está en el log real (visto 2026-11-15 al cerrar el juego).

    Sin esta señal el panel seguía afirmando «en partida» hasta que el log cumplía 90 s.
    """
    log_sintetico("GameInProgress", cerrar=True)
    log_juego.actualizar(force=True)
    assert log_juego.cerrado() is True
    assert log_juego.en_partida() is False
    assert log_juego.estado_ui()[0] is None


def test_si_el_juego_vuelve_a_arrancar_no_esta_cerrado(log_sintetico):
    ruta = log_sintetico("GameInProgress", cerrar=True)
    with open(ruta, "a", encoding="utf-8") as f:
        f.write("[HostStateManager] Host activate: Loading (dl_midtown)\n")
    log_juego._cache.update({"mtime": None, "size": None, "pos": 0})
    log_juego.actualizar(force=True)
    assert log_juego.cerrado() is False
    assert log_juego.estado_ui()[0] == "partida"


def test_en_menu_no_es_un_error(log_sintetico):
    log_sintetico("HeroSelection")
    log_juego.actualizar(force=True)
    fase, _ = log_juego.estado_ui()
    assert fase == "menu"


def test_log_viejo_no_afirma_nada(log_sintetico):
    """La última fase escrita de una sesión cerrada no vale como estado actual."""
    log_sintetico("GameInProgress", edad_s=600)
    fase, frescura = log_juego.estado_ui()
    assert fase is None
    assert frescura > 500


def test_sin_log_no_se_inventa(monkeypatch, tmp_path):
    monkeypatch.setattr(log_juego, "RUTA", str(tmp_path / "no-existe.log"))
    fase, frescura = log_juego.estado_ui()
    assert fase is None and frescura is None


def test_marco_perezoso_pide_solo_la_caja():
    """El marco no captura nada hasta que un lector pide una caja concreta."""
    pedidas = []

    def capturar(caja):
        pedidas.append(tuple(caja))
        return "recorte"

    marco = hud_rapido.MarcoPerezoso(capturador=capturar)
    assert pedidas == []                      # construirlo no cuesta una captura
    assert marco.crop((10, 20, 30, 40)) == "recorte"
    assert pedidas == [(10, 20, 30, 40)]
    assert marco.metricas() == {"capturas": 1, "errores": 0}


def test_marco_perezoso_falla_sin_tumbar_el_hilo():
    marco = hud_rapido.MarcoPerezoso(capturador=lambda caja: None)
    with pytest.raises(OSError):
        marco.crop((0, 0, 10, 10))
    assert marco.metricas() == {"capturas": 0, "errores": 1}

"""Identidad de la partida: de dónde sale el id y cuándo se puede creer.

Regla del relevo: si no hay certeza, se muestra fase y héroe y «sin datos», nunca una
partida falsa. Y no se gasta cuota de espectador en un id que no está validado.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from coach.fuentes import api_vivo  # noqa: E402


def _limpiar(monkeypatch):
    monkeypatch.setattr(api_vivo, "_cache",
                        {"match": None, "via": None, "detalle": "", "ts": 0.0})
    monkeypatch.setattr(api_vivo, "_vacios", 0)


def test_hud_y_console_log_de_acuerdo_no_gastan_api(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setattr(api_vivo, "_leer_hud", lambda: 134452212)
    monkeypatch.setattr(api_vivo, "_leer_log", lambda: 134452212)

    def _no_llamar(*a, **k):
        raise AssertionError("no debía preguntar a la API")

    monkeypatch.setattr(api_vivo.en_vivo, "partidas_con_broadcast", _no_llamar)
    monkeypatch.setattr(api_vivo.en_vivo, "partida_activa", _no_llamar)

    hallado = api_vivo.descubrir(cuenta=376225059, forzar=True)
    assert hallado["match"] == 134452212
    assert hallado["via"] == "hud+log"


def test_solo_el_console_log_sirve_como_candidato(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setattr(api_vivo, "_leer_hud", lambda: None)
    monkeypatch.setattr(api_vivo, "_leer_log", lambda: 134452212)
    monkeypatch.setattr(api_vivo.en_vivo, "partidas_con_broadcast",
                        lambda timeout=20: {134452212})
    hallado = api_vivo.descubrir(cuenta=None, forzar=True)
    assert hallado["match"] == 134452212
    assert hallado["via"] == "hud"


def test_si_no_coinciden_manda_el_console_log(monkeypatch, tmp_path):
    """El HUD se lee de una imagen; el console.log lo escribe el juego. Manda el texto."""
    from coach import telemetria

    _limpiar(monkeypatch)
    monkeypatch.setattr(telemetria, "RUTA", str(tmp_path / "tel.jsonl"))
    monkeypatch.setattr(api_vivo, "_leer_hud", lambda: 134358843)   # lectura mala
    monkeypatch.setattr(api_vivo, "_leer_log", lambda: 134452212)
    monkeypatch.setattr(api_vivo.en_vivo, "partidas_con_broadcast",
                        lambda timeout=20: {134452212})
    hallado = api_vivo.descubrir(cuenta=376225059, forzar=True)
    assert hallado["match"] == 134452212
    assert hallado["via"] == "hud"
    rechazos = [e for e in telemetria.leer(5, ruta=str(tmp_path / "tel.jsonl"))
                if e.get("rechazo")]
    assert rechazos and rechazos[-1]["candidato"] == 134358843


def test_la_cuenta_manda_sobre_un_hud_equivocado(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setattr(api_vivo, "_leer_hud", lambda: 134358843)
    monkeypatch.setattr(api_vivo, "_leer_log", lambda: None)
    monkeypatch.setattr(api_vivo.en_vivo, "partida_activa",
                        lambda cuenta, timeout=20: 134452212)
    hallado = api_vivo.descubrir(cuenta=376225059, forzar=True)
    assert hallado["match"] == 134452212
    assert hallado["via"] == "cuenta"


def test_la_decision_queda_en_telemetria(monkeypatch, tmp_path):
    from coach import telemetria

    _limpiar(monkeypatch)
    monkeypatch.setattr(telemetria, "RUTA", str(tmp_path / "tel.jsonl"))
    monkeypatch.setattr(api_vivo, "_leer_hud", lambda: 134452212)
    monkeypatch.setattr(api_vivo, "_leer_log", lambda: 134452212)
    api_vivo.descubrir(cuenta=376225059, forzar=True)
    eventos = telemetria.leer(5, ruta=str(tmp_path / "tel.jsonl"))
    assert eventos[-1]["via"] == "hud+log"
    assert eventos[-1]["match"] == 134452212

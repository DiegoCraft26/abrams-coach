"""Visión con respaldo: qué proveedor se usa y qué pasa cuando uno se cae.

Medido el 2026-11-09: huggingface contesta un cuadro de 33 kB en ~23 s y commandcode se
cae por tiempo de espera con ese mismo cuadro. De ahí el orden y el respaldo.
"""
import base64
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from coach.agente import proveedor as P  # noqa: E402


class Falso(P.ProveedorOpenAICompatible):
    """Proveedor que no sale a la red: apunta lo que le mandan y contesta lo que se le diga."""

    def __init__(self, nombre, falla=False, contenido='{"fase": "en_partida"}'):
        super().__init__("https://x", "m", "CLAVE_DE_PRUEBA", nombre)
        self.falla = falla
        self.contenido = contenido
        self.cuerpos = []
        self.llamadas = 0

    def _clave(self):
        return "clave-falsa"

    def _intentar(self, mensajes, herramientas, timeout_s):
        self.llamadas += 1
        self.cuerpos.append({"mensajes": mensajes, "timeout": timeout_s})
        if self.falla:
            raise P.ErrorProveedor(f"{self.nombre}: HTTP 504")
        return {"choices": [{"message": {"content": self.contenido}}],
                "usage": {"total_tokens": 42}}


def test_el_orden_de_vision_es_el_medido():
    assert [p.nombre for p in P.cadena_vision()] == ["huggingface", "commandcode"]


def test_el_local_no_entra_en_la_cadena_de_vision():
    assert "local-llama" not in [p.nombre for p in P.cadena_vision()]


def test_soporta_vision_distingue():
    assert P.soporta_vision(Falso("x")) is True
    assert P.soporta_vision(object()) is False


def test_la_imagen_viaja_como_data_url():
    prov = Falso("uno")
    prov.chat_vision(b"\xff\xd8jpeg-falso", "lee esto", sistema="eres un lector")
    mensajes = prov.cuerpos[0]["mensajes"]
    assert mensajes[0]["role"] == "system"
    contenido = mensajes[1]["content"]
    assert contenido[0]["type"] == "text"
    url = contenido[1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"\xff\xd8jpeg-falso"


def test_sin_reintento_por_defecto_en_vision():
    prov = Falso("uno", falla=True)
    with pytest.raises(P.ErrorProveedor):
        prov.chat_vision(b"x", "texto")
    assert prov.llamadas == 1      # no dos: la lectura de pantalla tiene respaldo


def test_el_respaldo_usa_el_segundo_si_el_primero_falla():
    caido = Falso("caido", falla=True)
    bueno = Falso("bueno")
    respaldo = P.RespaldoVision([caido, bueno])
    respuesta = respaldo.chat_vision(b"x", "texto")
    assert respuesta["usage"]["total_tokens"] == 42
    assert caido.llamadas == 1 and bueno.llamadas == 1
    assert respaldo.ultimo_bueno == "bueno"


def test_el_respaldo_no_usa_quien_no_tiene_clave():
    class SinClave(Falso):
        def _clave(self):
            return None

    sin_clave = SinClave("sinclave")
    bueno = Falso("bueno")
    P.RespaldoVision([sin_clave, bueno]).chat_vision(b"x", "texto")
    assert sin_clave.llamadas == 0
    assert bueno.llamadas == 1


def test_si_todos_fallan_dice_por_que():
    respaldo = P.RespaldoVision([Falso("a", falla=True), Falso("b", falla=True)])
    with pytest.raises(P.ErrorProveedor) as info:
        respaldo.chat_vision(b"x", "texto")
    assert "ningún proveedor contestó" in str(info.value)


def test_el_respaldo_dice_si_hay_clave():
    assert P.RespaldoVision([Falso("a")]).hay_clave() is True

    class Ninguno(Falso):
        def _clave(self):
            return None

    assert P.RespaldoVision([Ninguno("a")]).hay_clave() is False


def test_el_nombre_del_respaldo_es_informativo():
    respaldo = P.RespaldoVision([Falso("uno"), Falso("dos")])
    assert respaldo.nombre == "visión:uno+dos"

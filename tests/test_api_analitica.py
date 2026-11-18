"""Presupuesto y caché de la API de analítica: lo que impide quedarse sin cuota.

Un experimento con 25 héroes hace ~150 peticiones. Sin caché en disco eso se repite cada
vez, y un 429 deja al coach sin poder preguntar durante minutos u horas. Estas pruebas
falsean el transporte: no tocan la red.
"""
import json
import os

import pytest

from coach.fuentes import api_analitica as A


@pytest.fixture()
def limpio(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "CARPETA", str(tmp_path))
    monkeypatch.setattr(A, "ESTADO", str(tmp_path / "_presupuesto.json"))
    monkeypatch.setattr(A, "MIN_INTERVALO_S", 0.0)
    A._memoria.clear()
    A._estado.update({"llamadas": [], "hasta": 0.0, "errores": 0,
                      "servidas_de_cache": 0})
    return tmp_path


def test_la_segunda_peticion_sale_de_cache(limpio):
    llamadas = []

    def transporte(url, timeout):
        llamadas.append(url)
        return [{"item_id": 1, "wins": 10, "losses": 5}]

    a = A.pedir("/v1/analytics/item-stats", transporte=transporte, hero_id=6)
    b = A.pedir("/v1/analytics/item-stats", transporte=transporte, hero_id=6)
    assert a == b
    assert len(llamadas) == 1, "la segunda no debió tocar la red"
    assert A.presupuesto()["de_cache"] >= 1


def test_la_cache_sobrevive_al_proceso(limpio):
    """Otro proceso (o el coach reabierto) tiene que ver lo mismo sin red."""
    A.pedir("/v1/analytics/hero-stats", transporte=lambda u, t: {"ok": True}, hero_id=6)
    A._memoria.clear()                    # simula reinicio: solo queda el disco
    datos = A.pedir("/v1/analytics/hero-stats",
                    transporte=lambda u, t: pytest.fail("no debía llamar"),
                    hero_id=6)
    assert datos == {"ok": True}


def test_una_cache_corrupta_no_rompe(limpio):
    A.pedir("/v1/analytics/x", transporte=lambda u, t: {"ok": 1}, hero_id=1)
    for nombre in os.listdir(limpio):
        if nombre.endswith(".json") and nombre != "_presupuesto.json":
            (limpio / nombre).write_text("{no es json", encoding="utf-8")
    A._memoria.clear()
    datos = A.pedir("/v1/analytics/x", transporte=lambda u, t: {"ok": 2}, hero_id=1)
    assert datos == {"ok": 2}


def test_tope_por_hora_se_respeta(limpio, monkeypatch):
    monkeypatch.setattr(A, "MAX_POR_HORA", 2)
    veces = []
    for i in range(3):
        try:
            A.pedir("/v1/analytics/y", transporte=lambda u, t: {"n": i}, hero_id=i)
            veces.append(i)
        except A.PresupuestoAgotado as exc:
            assert "tope" in str(exc)
    assert len(veces) == 2, "la tercera debió rebotar en el tope"


def test_un_429_cierra_la_puerta_el_tiempo_que_pida(limpio):
    def transporte(url, timeout):
        import urllib.error
        raise urllib.error.HTTPError(url, 429, "Too Many Requests",
                                     {"retry-after": "120"}, None)

    with pytest.raises(Exception):
        A.pedir("/v1/analytics/z", transporte=transporte, hero_id=1)
    assert A.presupuesto()["espera_hasta"] > 60
    with pytest.raises(A.PresupuestoAgotado):
        A.pedir("/v1/analytics/z", transporte=lambda u, t: {}, hero_id=1)


def test_forzar_se_salta_la_cache_no_el_presupuesto(limpio):
    llamadas = []

    def transporte(url, timeout):
        llamadas.append(url)
        return {"v": len(llamadas)}

    A.pedir("/v1/analytics/f", transporte=transporte, hero_id=1)
    segundo = A.pedir("/v1/analytics/f", transporte=transporte, forzar=True, hero_id=1)
    assert len(llamadas) == 2
    assert segundo == {"v": 2}


def test_los_parametros_forman_parte_de_la_clave(limpio):
    """Dos héroes distintos no pueden compartir la misma entrada de caché."""
    datos = {"hero_id": 6, "wins": 1}
    A.pedir("/v1/analytics/item-stats", transporte=lambda u, t: datos, hero_id=6)
    otro = A.pedir("/v1/analytics/item-stats", transporte=lambda u, t: {"hero_id": 7},
                   hero_id=7)
    assert otro == {"hero_id": 7}


def test_el_estado_se_guarda_en_disco(limpio):
    A.pedir("/v1/analytics/e", transporte=lambda u, t: {"ok": 1}, hero_id=1)
    with open(A.ESTADO, encoding="utf-8") as f:
        guardado = json.load(f)
    assert len(guardado["llamadas"]) == 1

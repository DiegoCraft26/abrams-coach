"""Telemetría de identidad: lo que se creyó, por qué vía y qué se rechazó.

Sin este registro, un panel que enseña una partida que no es se discute de memoria. Lo
que se prueba aquí es que el apunte no puede tumbar el bucle y que el resumen cuenta lo
que de verdad pasó.
"""
import json
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from coach import telemetria  # noqa: E402


def test_anota_y_lee(tmp_path):
    ruta = tmp_path / "tel.jsonl"
    telemetria.anotar("descubrir", ruta=str(ruta), match=123, via="hud", rechazo=False,
                      detalle="id del HUD verificado con la cuenta")
    lineas = telemetria.leer(10, ruta=str(ruta))
    assert len(lineas) == 1
    assert lineas[0]["match"] == 123
    assert lineas[0]["via"] == "hud"
    assert lineas[0]["evento"] == "descubrir"
    assert isinstance(lineas[0]["ts"], float)


def test_valores_raros_no_revientan(tmp_path):
    ruta = tmp_path / "tel.jsonl"
    telemetria.anotar("x", ruta=str(ruta), objeto={"a": 1}, lista=[1, 2])
    dato = telemetria.leer(1, ruta=str(ruta))[0]
    assert dato["objeto"] == "{'a': 1}"      # se guarda como texto, no rompe el JSON


def test_el_resumen_cuenta_vias_y_rechazos(tmp_path):
    ruta = tmp_path / "tel.jsonl"
    telemetria.anotar("descubrir", ruta=str(ruta), match=1, via="hud")
    telemetria.anotar("descubrir", ruta=str(ruta), match=2, via="cuenta")
    telemetria.anotar("hud_rechazado", ruta=str(ruta), candidato=99, via="hud",
                      rechazo=True)
    resumen = telemetria.resumen(ruta=str(ruta))
    assert resumen["eventos"] == 3
    assert resumen["por_via"]["hud"] == 2
    assert resumen["rechazos"] == 1
    assert resumen["ultimo"]["evento"] == "hud_rechazado"


def test_un_archivo_inexistente_devuelve_vacio(tmp_path):
    assert telemetria.leer(5, ruta=str(tmp_path / "no-existe.jsonl")) == []
    assert telemetria.resumen(ruta=str(tmp_path / "no-existe.jsonl"))["eventos"] == 0


def test_una_linea_corrupta_se_salta(tmp_path):
    ruta = tmp_path / "tel.jsonl"
    ruta.write_text('{"evento": "buena", "via": "hud"}\n{rota\n', encoding="utf-8")
    assert len(telemetria.leer(10, ruta=str(ruta))) == 1


def test_no_revienta_si_no_puede_escribir(tmp_path):
    # Ruta dentro de un archivo (imposible de crear): debe devolver, no lanzar.
    archivo = tmp_path / "bloqueo"
    archivo.write_text("x", encoding="utf-8")
    telemetria.anotar("x", ruta=str(archivo / "sub" / "tel.jsonl"))


def test_el_descubrimiento_apunta_su_decision(tmp_path, monkeypatch):
    """Toda decisión de identidad pasa por `_guardar`: ahí se anota."""
    from coach.fuentes import api_vivo

    ruta = tmp_path / "tel.jsonl"
    monkeypatch.setattr(telemetria, "RUTA", str(ruta))
    monkeypatch.setattr(api_vivo, "_cache",
                        {"match": None, "via": None, "detalle": "", "ts": 0.0})
    hallado = api_vivo._guardar(134425462, "hud", "match id del HUD verificado")
    assert hallado["match"] == 134425462
    eventos = telemetria.leer(5, ruta=str(ruta))
    assert eventos[-1]["match"] == 134425462
    assert eventos[-1]["via"] == "hud"


def test_api_identidad_sirve_el_resumen(tmp_path, monkeypatch):
    from coach import servidor as S

    ruta = tmp_path / "tel.jsonl"
    monkeypatch.setattr(telemetria, "RUTA", str(ruta))
    telemetria.anotar("descubrir", ruta=str(ruta), match=77, via="cuenta")

    srv = S.arrancar(8096)
    try:
        with urllib.request.urlopen("http://127.0.0.1:8096/api/identidad",
                                    timeout=5) as r:
            datos = json.loads(r.read().decode())
    finally:
        srv.shutdown()
        srv.server_close()
    assert datos["telemetria"]["por_via"]["cuenta"] == 1
    assert datos["ultimos"][-1]["match"] == 77
    assert "console" in datos and "descubrimiento" in datos

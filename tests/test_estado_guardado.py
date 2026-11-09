"""El respaldo en disco del último estado: lo que se enseña cuando el coach no está."""
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from coach import estado_guardado  # noqa: E402


def test_guardar_y_cargar_da_la_vuelta(tmp_path):
    destino = tmp_path / "estado.json"
    assert estado_guardado.guardar({"t": 423, "oro": 1200}, ruta=destino, forzar=True)
    datos, edad = estado_guardado.cargar(destino)
    assert datos == {"t": 423, "oro": 1200}
    assert 0 <= edad < 5


def test_la_edad_se_calcula_con_el_reloj_de_ahora(tmp_path):
    destino = tmp_path / "estado.json"
    # Un estado escrito hace dos minutos no puede parecer recién leído.
    destino.write_text(json.dumps({"ts": time.time() - 120, "datos": {"t": 100}}),
                       encoding="utf-8")
    datos, edad = estado_guardado.cargar(destino)
    assert datos == {"t": 100}
    assert 119 <= edad <= 125


def test_archivo_corrupto_no_revienta(tmp_path):
    destino = tmp_path / "estado.json"
    destino.write_text("{no es json", encoding="utf-8")
    assert estado_guardado.cargar(destino) == (None, None)
    assert estado_guardado.como_respaldo(destino) is None


def test_sin_archivo_no_hay_respaldo(tmp_path):
    assert estado_guardado.como_respaldo(tmp_path / "no-existe.json") is None


def test_respaldo_demasiado_viejo_se_descarta(tmp_path):
    destino = tmp_path / "estado.json"
    destino.write_text(json.dumps({"ts": time.time() - 600,
                                   "datos": {"t": 100, "mensaje": "en partida"}}),
                       encoding="utf-8")
    assert estado_guardado.como_respaldo(destino, umbral_s=30) is None


def test_respaldo_marca_origen_y_edad(tmp_path):
    destino = tmp_path / "estado.json"
    estado_guardado.guardar({"t": 200, "mensaje": "en partida"}, ruta=destino, forzar=True)
    respaldo = estado_guardado.como_respaldo(destino)
    assert respaldo["origen"] == "guardado"
    assert respaldo["rancio"] is True
    assert "guardado hace" in respaldo["mensaje"]


def test_no_guarda_cosas_que_no_son_dict(tmp_path):
    destino = tmp_path / "estado.json"
    assert estado_guardado.guardar(None, ruta=destino, forzar=True) is False
    assert not destino.exists()


def test_el_intervalo_evita_escribir_en_cada_vuelta(tmp_path):
    destino = tmp_path / "estado.json"
    estado_guardado.guardar({"t": 1}, ruta=destino, forzar=True)
    assert estado_guardado.guardar({"t": 2}, ruta=destino) is False
    datos, _ = estado_guardado.cargar(destino)
    assert datos == {"t": 1}


def test_el_servidor_sirve_el_respaldo_si_el_coach_no_publico(tmp_path, monkeypatch):
    """Con el coach recién arrancado y sin publicar, /api/estado dice de dónde viene."""
    import json as _json
    import threading
    import urllib.request

    from coach import servidor as S

    destino = tmp_path / "estado.json"
    # Guardado hace 20 s: más viejo que el umbral de rancio (8 s) y más nuevo que el de
    # descarte del respaldo (30 s). Es el caso real de un coach que se acaba de caer.
    destino.write_text(_json.dumps({"ts": time.time() - 20,
                                    "datos": {"listo": True, "t": 300, "oro": 900,
                                              "mensaje": "en partida"}}),
                       encoding="utf-8")
    monkeypatch.setattr(estado_guardado, "RUTA", str(destino))

    monkeypatch.setattr(S.EST, "ts", 0.0)
    monkeypatch.setattr(S.EST, "ultimo", {"listo": False, "mensaje": "esperando datos"})
    srv = S.arrancar(8094)
    try:
        with urllib.request.urlopen("http://127.0.0.1:8094/api/estado", timeout=5) as r:
            datos = _json.loads(r.read().decode())
    finally:
        srv.shutdown()
        srv.server_close()
    assert datos.get("origen") == "guardado"
    assert datos.get("oro") == 900
    assert datos.get("rancio") is True
    assert "guardado hace" in datos.get("mensaje", "")

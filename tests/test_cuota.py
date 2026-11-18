"""El cupo local: la app no puede gastarse la cuota de espectador por reintentos.

Estas pruebas fijan el contrato que evita el fallo del 2026-11-18 (seis aperturas en un
minuto dejaron el panel muerto una hora):

- sin fichas no se llama, y se dice cuánto falta;
- el conteo sobrevive al reinicio (era la vía por la que cada arranque metía una más);
- un archivo corrupto no rompe el arranque;
- devolver una ficha no pasa de la capacidad;
- la recarga respeta la tasa por hora.
"""
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import cuota            # noqa: E402


def _limpio(tmp_path, monkeypatch, **permiso):
    monkeypatch.setattr(cuota, "RUTA", str(tmp_path / "cupo.json"))
    monkeypatch.setattr(cuota, "_baldes", {})
    monkeypatch.setattr(cuota, "_cargado", True)
    monkeypatch.delenv("ABRAMS_CUPO_ESPECTADOR_MAX", raising=False)
    monkeypatch.delenv("ABRAMS_CUPO_ESPECTADOR_TASA", raising=False)
    for clave, valor in permiso.items():
        monkeypatch.setenv(f"ABRAMS_CUPO_ESPECTADOR_{clave}", str(valor))


def test_arranca_con_la_capacidad_y_se_agota(tmp_path, monkeypatch):
    _limpio(tmp_path, monkeypatch)
    assert cuota.disponible("espectador") == 2.0
    assert cuota.tomar("espectador") is True
    assert cuota.tomar("espectador") is True
    assert cuota.tomar("espectador") is False
    assert cuota.faltan_s("espectador") > 0


def test_el_conteo_sobrevive_al_reinicio(tmp_path, monkeypatch):
    _limpio(tmp_path, monkeypatch)
    assert cuota.tomar("espectador")
    assert cuota.tomar("espectador")
    # Reinicio del coach: se vacía la memoria pero se conserva el archivo.
    monkeypatch.setattr(cuota, "_baldes", {})
    monkeypatch.setattr(cuota, "_cargado", False)
    assert cuota.tomar("espectador") is False, "reiniciar no devuelve fichas"
    assert cuota.faltan_s("espectador") > 0


def test_un_archivo_corrupto_no_rompe_el_arranque(tmp_path, monkeypatch):
    _limpio(tmp_path, monkeypatch)
    (tmp_path / "cupo.json").write_text("{esto no es json", encoding="utf-8")
    monkeypatch.setattr(cuota, "_cargado", False)
    # No lanza y arranca con la capacidad completa.
    assert cuota.tomar("espectador") is True


def test_devolver_no_pasa_de_la_capacidad(tmp_path, monkeypatch):
    _limpio(tmp_path, monkeypatch)
    for _ in range(10):
        cuota.devolver("espectador")
    assert cuota.disponible("espectador") == 2.0


def test_la_recarga_respeta_la_tasa(tmp_path, monkeypatch):
    _limpio(tmp_path, monkeypatch, TASA="6")
    monkeypatch.setattr(cuota, "RUTA", str(tmp_path / "cupo.json"))
    cuota.tomar("espectador")
    cuota.tomar("espectador")
    base = cuota._baldes["espectador"]["ts"]
    # Media hora después hay 3 fichas exactas (6/hora), pero el tope es 2.
    monkeypatch.setattr(cuota.time, "time", lambda: base + 1800)
    assert cuota.disponible("espectador") == 2.0
    # Diez minutos dan 1 ficha: justo para volver a llamar.
    monkeypatch.setattr(cuota.time, "time", lambda: base + 600)
    assert cuota.tomar("espectador") is True


def test_el_estado_es_legible_para_la_ui(tmp_path, monkeypatch):
    _limpio(tmp_path, monkeypatch)
    cuota.tomar("espectador")
    foto = cuota.estado()["espectador"]
    assert foto["fichas"] == 1.0
    assert foto["capacidad"] == 2.0
    assert foto["por_hora"] == 6.0


def test_la_escritura_es_atomica_y_deja_el_anterior(tmp_path, monkeypatch):
    _limpio(tmp_path, monkeypatch)
    assert cuota.tomar("espectador")
    datos = json.loads((tmp_path / "cupo.json").read_text(encoding="utf-8"))
    assert datos["espectador"]["fichas"] == 1.0
    assert not (tmp_path / "cupo.json.tmp").exists()

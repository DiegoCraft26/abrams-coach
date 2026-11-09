"""El vigilante tiene que saber distinguir un panel vivo de un zombi.

Regresión del 2026-11-09: el panel murió, su proceso quedó como zombi y `os.kill(pid, 0)`
seguía diciendo que existía. El vigilante creía tener panel y no lo reabría nunca: el
panel desaparecía de la pantalla y del registro, sin más.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "herramientas"))

import vigilar  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _log_aparte(tmp_path, monkeypatch):
    """Los tests no escriben en el registro real del vigilante (/tmp/abrams-vigilar.log)."""
    monkeypatch.setattr(vigilar, "LOG", str(tmp_path / "vigilar.log"))


def test_pid_inexistente_no_es_panel():
    assert vigilar._es_panel(999_999) is False


def test_este_proceso_no_es_el_panel():
    # Está vivo, pero no es el panel: la línea de órdenes lo delata.
    assert vigilar._es_panel(os.getpid()) is False


def test_un_zombi_no_cuenta_como_panel():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        time.sleep(0.4)
        # Sin poll() ni wait(): el hijo queda en estado Z, que es exactamente lo que
        # confundía al vigilante.
        assert os.kill(p.pid, 0) is None
        assert vigilar._es_panel(p.pid) is False
    finally:
        p.wait(timeout=10)


def test_describir_fin_nombra_la_senal():
    assert "SIGKILL" in vigilar.describir_fin(-9)
    assert "falta de memoria" in vigilar.describir_fin(-9)
    assert vigilar.describir_fin(0) == "código 0"
    assert vigilar.describir_fin(None) == "sigue vivo"


def test_revisar_hijos_anota_y_descarta():
    vivo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    muerto = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
    try:
        muerto.wait(timeout=10)
        quedan = vigilar.revisar_hijos([vivo, muerto])
        assert quedan == [vivo]
    finally:
        vivo.kill()
        vivo.wait(timeout=10)


def test_un_solo_vigilante_a_la_vez(tmp_path):
    """El 2026-11-09 quedó un vigilante viejo junto al servicio y abrían dos paneles."""
    ruta = tmp_path / "vigilar.lock"
    primero = vigilar.tomar_bloqueo(str(ruta))
    assert primero is not None
    try:
        assert vigilar.tomar_bloqueo(str(ruta)) is None
    finally:
        primero.close()
    segundo = vigilar.tomar_bloqueo(str(ruta))
    assert segundo is not None
    segundo.close()


def test_el_modo_silencio_se_lee_de_un_archivo(tmp_path):
    marca = tmp_path / "silencio"
    assert vigilar.en_silencio(str(marca)) is False
    marca.write_text("", encoding="utf-8")
    assert vigilar.en_silencio(str(marca)) is True


def test_el_freno_de_reapertura_existe():
    # Cinco minutos entre reaperturas: sin freno, un panel que se cae solo entra en bucle.
    assert vigilar.MIN_ENTRE_REAPERTURAS_S >= 60

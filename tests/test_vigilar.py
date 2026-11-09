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

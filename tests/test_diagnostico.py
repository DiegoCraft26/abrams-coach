"""El registro de muerte tiene que dejar constancia de verdad.

Se prueban los tres finales que importan: excepción propia, señal de fuera y arranque. Si
esto pasa, un panel que desaparece deja al menos una línea con el motivo en vez de nada.
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _correr(codigo):
    entorno = dict(os.environ)
    entorno["PYTHONPATH"] = str(RAIZ) + os.pathsep + entorno.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-c", codigo], capture_output=True,
                          text=True, env=entorno, timeout=30, cwd=str(RAIZ))


def _lanzar(codigo):
    entorno = dict(os.environ)
    entorno["PYTHONPATH"] = str(RAIZ) + os.pathsep + entorno.get("PYTHONPATH", "")
    return subprocess.Popen([sys.executable, "-c", codigo], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=entorno, cwd=str(RAIZ))


def test_arranque_y_excepcion_quedan_anotados(tmp_path):
    archivo = tmp_path / "crash.log"
    r = _correr(f"""
from coach import diagnostico
diagnostico.activar("prueba", {str(archivo)!r})
raise RuntimeError("reventó de prueba")
""")
    assert r.returncode == 1, r.stderr
    texto = archivo.read_text(encoding="utf-8")
    assert "arranque prueba" in texto
    assert "RuntimeError: reventó de prueba" in texto
    assert "salida limpia" in texto


def test_sigterm_queda_anotado(tmp_path):
    archivo = tmp_path / "crash.log"
    p = _lanzar(f"""
import time
from coach import diagnostico
diagnostico.activar("prueba", {str(archivo)!r})
time.sleep(30)
""")
    try:
        # Se espera a que escriba la línea de arranque: si no, la señal llega antes de
        # que el manejador esté puesto y se pierde la prueba.
        for _ in range(100):
            if archivo.exists() and "arranque" in archivo.read_text(encoding="utf-8"):
                break
            time.sleep(0.05)
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=20)
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=20)
    texto = archivo.read_text(encoding="utf-8")
    assert "señal SIGTERM recibida" in texto
    # La señal relanzada mata el proceso: no debe quedar como salida limpia.
    assert "salida limpia" not in texto


def test_rss_se_puede_leer():
    sys.path.insert(0, str(RAIZ))
    from coach import diagnostico
    valor = diagnostico.rss_mb()
    assert valor is None or valor > 0


def test_activar_es_idempotente(tmp_path):
    archivo = tmp_path / "crash.log"
    r = _correr(f"""
from coach import diagnostico
a = diagnostico.activar("prueba", {str(archivo)!r})
b = diagnostico.activar("prueba", {str(archivo)!r})
print("ruta", a, b)
""")
    assert r.returncode == 0, r.stderr
    texto = archivo.read_text(encoding="utf-8")
    assert texto.count("arranque prueba") == 1

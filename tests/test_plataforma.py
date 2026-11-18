"""El motor no depende de GTK: la invariante que hace posible Windows algún día.

En Linux la UI es GTK4 y la captura es KWin. En Windows no existe ninguna de las dos, así
que todo lo que no sea interfaz tiene que funcionar sin `gi`. Esto no se comprueba
leyendo el código: se comprueba **importando de verdad** con un `gi` falso que falla, en
un subproceso limpio. Si alguien mete un `import gi` en el motor, esta prueba lo caza.
"""
import os
import pathlib
import subprocess
import sys
import tempfile

RAIZ = pathlib.Path(__file__).resolve().parent.parent

MODULOS_MOTOR = [
    "coach.estado", "coach.motor", "coach.motor_api", "coach.valor", "coach.modelo",
    "coach.historico", "coach.conocimiento", "coach.servidor", "coach.decision",
]


def _con_gi_roto(codigo: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        (pathlib.Path(tmp) / "gi.py").write_text(
            "raise ImportError('gi no disponible en esta plataforma')\n", encoding="utf-8")
        # `os.pathsep` y el entorno heredado: en Windows el separador es ";" y sin
        # SYSTEMROOT el intérprete ni arranca. La prueba tiene que correr en los dos.
        entorno = dict(os.environ)
        entorno["PYTHONPATH"] = tmp + os.pathsep + str(RAIZ)
        return subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, text=True,
                              capture_output=True, env=entorno, timeout=120)


def test_el_motor_importa_sin_gtk():
    codigo = "import " + ", ".join(MODULOS_MOTOR) + "; print('ok')"
    p = _con_gi_roto(codigo)
    assert p.returncode == 0, p.stderr[-1200:]
    assert "ok" in p.stdout


def test_el_panel_web_es_html_puro_sin_gtk():
    p = _con_gi_roto("from coach.ui.web import PAGINA; print(len(PAGINA))")
    assert p.returncode == 0, p.stderr[-1200:]


def test_solo_captura_kwin_importa_gi_fuera_de_la_ui():
    """Invariante estática: si aparece otro, es que la lógica se metió en la plataforma."""
    culpables = []
    for p in sorted((RAIZ / "coach").rglob("*.py")):
        if "ui" in p.parts or "__pycache__" in p.parts:
            continue
        texto = p.read_text(errors="ignore")
        for linea in texto.splitlines():
            s = linea.strip()
            if s.startswith("import gi") or s.startswith("from gi."):
                culpables.append(p.relative_to(RAIZ).as_posix())
                break
    assert culpables == ["coach/fuentes/captura_kwin.py"], culpables


def test_la_captura_se_importa_sin_kwin():
    """Sin KWin (Windows), el módulo de captura debe importarse, no estallar."""
    import importlib.util
    if importlib.util.find_spec("PIL") is None:
        import pytest
        pytest.skip("Pillow no está en este entorno; la app real lo exige")
    # `captura_kwin` importa `gi` dentro de la función, así que el módulo carga sin él;
    # lo que no puede pasar es que el import de la captura estalle en una máquina sin GTK.
    p = _con_gi_roto("from coach.fuentes import captura; print('ok')")
    assert p.returncode == 0, p.stderr[-1200:]
    assert "ok" in p.stdout

"""La revisión de estabilidad tiene que reconocer los procesos como son.

La primera versión no vio el coach porque la salida de `ps` va con sangría y el proceso
era `python3 run.py` (sin `-u`): dijo «no corre» con el coach corriendo. Un diagnóstico
que miente es peor que no tenerlo.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "herramientas"))

import revisar_estabilidad as RE  # noqa: E402

PS_REAL = """    PID     ELAPSED ARGS
 1069700       23:15 python3 run.py --fuente vivo --puerto 8090
 1069742       23:13 python3 panel_nativo.py --url http://127.0.0.1:8090
 1069701       23:15 python3 -u run.py --fuente vivo --puerto 8090
"""


def test_reconoce_el_coach_con_y_sin_menos_u():
    datos = RE.procesos(PS_REAL)
    assert datos["coach"] is True
    assert datos["coach_uptime"] in ("23:15",)


def test_reconoce_el_panel():
    datos = RE.procesos(PS_REAL)
    assert datos["panel"] is True
    assert datos["panel_uptime"] == "23:13"


def test_sin_procesos_no_se_inventa_nada():
    datos = RE.procesos("    PID ELAPSED ARGS\n  1  00:01 bash\n")
    assert datos["coach"] is False and datos["panel"] is False


def test_lee_los_finales_del_panel(tmp_path):
    archivo = tmp_path / "crash.log"
    archivo.write_text(
        "2026-11-09 12:41:08 [pid 982639] arranque panel: padre 982630\n"
        "2026-11-09 13:27:53 [pid 982639] salida limpia (atexit)\n", encoding="utf-8")
    finales = RE.final_del_panel(str(archivo))
    assert "salida limpia (atexit)" in finales
    assert all("pid" not in f for f in finales)


def test_sin_archivo_de_finales_devuelve_vacio(tmp_path):
    assert RE.final_del_panel(str(tmp_path / "no-existe.log")) == []

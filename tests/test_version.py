"""¿La app abierta corre el código actual? El veredicto tiene que ser honesto.

Sin esto, la respuesta dependía de acordarse de haber reiniciado. Lo que se prueba
aquí es la lógica, no git: los tres insumos (disco, marcador, procesos) se falsean.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from coach import version  # noqa: E402


def _disco(commit="abc1234", huella="hhhh", sucio=False, remoto=None):
    return {
        "git": True, "commit": commit, "commit_completo": commit + "fff",
        "rama": "master", "sucio": sucio, "sucio_detalle": [],
        "fecha": "2026-11-18 00:00:00 -0600", "remoto": remoto or {
            "adelante": 0, "atras": 0, "al_dia": True, "upstream": "origin/master"},
        "huella": huella,
    }


def _marcador(commit="abc1234", huella="hhhh", pid=None):
    return {"arranque": "2026-11-18 01:00:00", "pid": pid, "commit": commit,
            "rama": "master", "huella": huella, "sucio": False, "version": "v0.7.1"}


def _fijar(monkeypatch, disco=None, marcador=None, procesos=None):
    monkeypatch.setattr(version, "estado_git", lambda: disco or _disco())
    monkeypatch.setattr(version, "leer_marcador", lambda archivo=None: marcador)
    monkeypatch.setattr(version, "procesos_en_vivo", lambda: procesos or [])
    monkeypatch.setattr(version, "leer_version", lambda: "v0.7.1")


def test_huella_cambia_con_el_contenido(tmp_path):
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("x = 1\n")
    b.write_text("x = 2\n")
    antes = version.huella([str(a)])
    b.write_text("x = 3\n")
    assert version.huella([str(a)]) == antes
    a.write_text("x = 9\n")
    assert version.huella([str(a)]) != antes


def test_coincide_si_commit_y_huella_son_los_del_arranque(monkeypatch):
    _fijar(monkeypatch, marcador=_marcador())
    assert version.comparar()["veredicto"] == "si"


def test_editar_sin_commitear_cambia_la_huella_y_delata_la_app_vieja(monkeypatch):
    _fijar(monkeypatch, disco=_disco(huella="nnnn"), marcador=_marcador(huella="hhhh"))
    datos = version.comparar()
    assert datos["veredicto"] == "no"
    assert "reiníciala" in datos["texto"]


def test_commit_nuevo_tambien_delata_la_app_vieja(monkeypatch):
    _fijar(monkeypatch, disco=_disco(commit="def5678", huella="hhhh"),
           marcador=_marcador(commit="abc1234", huella="hhhh"))
    assert version.comparar()["veredicto"] == "no"


def test_marcador_de_una_instancia_muerta_no_cuenta(monkeypatch):
    _fijar(monkeypatch, marcador=_marcador(pid=999999))
    datos = version.comparar()
    assert datos["veredicto"] == "sin_app"
    assert "ya no corre" in (datos["aviso"] or "")


def test_sin_marcador_pero_con_proceso_reciente_es_probable_si(monkeypatch, tmp_path):
    import time

    archivo = tmp_path / "motor.py"
    archivo.write_text("x = 1\n")
    monkeypatch.setattr(version, "rutas_fuente", lambda: [str(archivo)])
    ahora = time.time()
    _fijar(monkeypatch, marcador=None,
           procesos=[{"pid": 1, "cmd": "python3 run.py", "inicio": ahora}])
    datos = version.comparar()
    assert datos["veredicto"] == "probable_si"
    assert datos["aviso"]


def test_proceso_anterior_al_ultimo_cambio_es_probable_no(monkeypatch, tmp_path):
    import time

    archivo = tmp_path / "motor.py"
    archivo.write_text("x = 1\n")
    monkeypatch.setattr(version, "rutas_fuente", lambda: [str(archivo)])
    _fijar(monkeypatch, marcador=None,
           procesos=[{"pid": 1, "cmd": "python3 run.py", "inicio": time.time() - 3600}])
    assert version.comparar()["veredicto"] == "probable_no"


def test_el_rezago_del_remoto_se_nombra(monkeypatch):
    _fijar(monkeypatch, disco=_disco(remoto={"adelante": 0, "atras": 2,
                                             "al_dia": False,
                                             "upstream": "origin/master"}),
           marcador=_marcador())
    datos = version.comparar()
    assert datos["veredicto"] == "si"
    assert "2 commits atrás" in datos["texto"]


def test_resumen_no_revienta_sin_app(monkeypatch):
    _fijar(monkeypatch, marcador=None)
    texto = version.resumen()
    assert "app abierta : ninguna" in texto

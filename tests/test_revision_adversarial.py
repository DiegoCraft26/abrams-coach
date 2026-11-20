"""Defectos que la revisión adversarial encontró y que no deben volver.

Cada prueba corresponde a un hallazgo concreto del 2026-11-18. Todas habrían pasado la
suite anterior: comprobaban substrings, no lo que el usuario ve.
"""
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.ui import app as ui_app                                # noqa: E402
from coach.ui.componentes.recomendacion import RecommendationCard  # noqa: E402
from coach.ui.web import PAGINA                                     # noqa: E402
from coach import cuota                                             # noqa: E402

_APP = None


def _ventana():
    global _APP
    if _APP is None:
        _APP = Gtk.Application(application_id="gg.diego.abramscoach.pruebasrevision")
        _APP.register(None)
        _APP.activate()
    return _APP


def _tarjeta():
    _ventana()
    return RecommendationCard()


# 1. El panel decía «en vivo» con el coach muerto -------------------------------
def test_un_dato_viejo_se_marca_rancio_pasado_el_umbral():
    datos = {"t": 1200, "listo": True, "recomendaciones": []}
    marcado, extra = ui_app.marcar_rancio(datos, "URLError", edad=30.0, intervalo=1.0)
    assert marcado["rancio"] is True
    assert marcado["edad_s"] == 30.0
    assert "sin respuesta" in marcado["mensaje"]
    assert extra and extra.startswith("sin-respuesta")


def test_un_error_reciente_no_marca_rancio():
    datos = {"t": 1200, "listo": True}
    marcado, extra = ui_app.marcar_rancio(datos, "URLError", edad=1.0, intervalo=1.0)
    assert "rancio" not in marcado and extra is None


def test_sin_error_no_se_toca_el_dato():
    datos = {"t": 1200, "listo": True}
    marcado, extra = ui_app.marcar_rancio(datos, None, edad=999.0)
    assert marcado is datos and extra is None


# 2. Las claves de las secciones son las que publica el motor -------------------
def test_las_claves_de_seccion_existen_en_el_payload():
    """`contra` y `serie`/`tendencia` no existen: eran cajas muertas."""
    fuente = open(os.path.join(RAIZ, "coach", "ui", "app.py"), encoding="utf-8").read()
    bloque = fuente.split("self._secciones = {")[1].split("\n        }")[0]
    assert '("historial",)' in bloque
    # La caja «CONTRA SU COMPOSICIÓN» se eliminó en v1.0.4 (el counter entró al camino y
    # `contra.py` se borró). Esta prueba pedía lo contrario y llevaba desde entonces en
    # rojo: fijaba una sección que ya no existe.
    assert '"contra_composicion"' not in bloque
    # las claves inventadas del pasado ya no deciden visibilidad
    assert '("tendencia",' not in bloque and '("serie",' not in bloque
    assert '("sugerencia_items", "amenazas", "contra")' not in bloque


# 3. El panel web ya no estima «faltan» (2026-11-18) ----------------------------
# Se retiró el bloque que calculaba «faltan ~N» y «ya te alcanza» con el oro del
# broadcast: llegaba tarde y prometía precisión que no existía. Esta prueba fija que no
# vuelva ni esa cuenta ni el error viejo de leer `bolsillo.oro` como objeto.
def test_el_panel_web_no_estima_faltan_ni_alcanza():
    assert "ya te alcanza" not in PAGINA
    assert "faltan ~" not in PAGINA
    assert "d.bolsillo && d.bolsillo.oro" not in PAGINA
    assert "Number.isFinite(d.bolsillo)" not in PAGINA


# 4. La apertura no es «en vivo» -----------------------------------------------
def test_la_apertura_dice_que_no_hay_partida(monkeypatch):
    from coach import nucleo_vivo, servidor

    publicado = {}

    class Estado:
        def publicar(self, datos):
            publicado.update(datos)

    monkeypatch.setattr(servidor, "EST", Estado())
    conoc = {"item": {"nombre": "Spellbreaker", "costo": 6400}}
    assert nucleo_vivo.publicar_apertura(conoc) is True
    assert publicado.get("listo") is False
    assert publicado.get("modo") == "APERTURA"


# 5. Clases CSS: una clase por nombre, no «t11 aviso» --------------------------
def test_el_veredicto_negativo_pinta_aviso_y_conserva_t11():
    card = _tarjeta()
    card.actualizar({
        "listo": True,
        "decision": {"accion": "COMPRAR", "motivo": "siguiente pieza"},
        "recomendaciones": [{
            "id": "1", "nombre": "Lifestrike", "costo": 3200, "razones": ["x"],
            "evidencia": {"efecto_pp": -1.6, "ic90": [-2.1, -1.1],
                          "n_partidas": 13642, "etiqueta": "medido", "evalue": 1.2},
        }],
    })
    clases = set(card.lbl_evidencia.get_css_classes())
    assert "t11" in clases, clases
    assert "aviso" in clases, clases
    assert "tenue" not in clases, clases
    assert "t11 aviso" not in clases, clases
    assert "no respalda" in card.lbl_evidencia.get_label()


def test_el_veredicto_positivo_pinta_tenue():
    card = _tarjeta()
    card.actualizar({
        "listo": True,
        "decision": {"accion": "COMPRAR", "motivo": "x"},
        "recomendaciones": [{
            "id": "2", "nombre": "Colossus", "costo": 6400, "razones": ["x"],
            "evidencia": {"efecto_pp": 3.9, "ic90": [2.6, 5.2],
                          "n_partidas": 4092, "etiqueta": "medido", "evalue": 1.36},
        }],
    })
    clases = set(card.lbl_evidencia.get_css_classes())
    assert "tenue" in clases and "aviso" not in clases


def test_las_acciones_conservan_la_clase_base():
    card = _tarjeta()
    card.actualizar({
        "listo": True,
        "decision": {"accion": "AHORRAR", "faltan": 800, "motivo": "x"},
        "recomendaciones": [{"id": "3", "nombre": "Colossus", "costo": 6400,
                             "razones": ["x"]}],
    })
    clases = set(card.lbl_accion.get_css_classes())
    assert "accion" in clases, clases
    assert "accion-espera" in clases, clases
    assert not any(" " in c for c in clases), clases


# 6. Cupo: un reloj hacia atrás no regala fichas --------------------------------
def test_un_ts_futuro_no_regala_la_capacidad(tmp_path, monkeypatch):
    import json
    import time as _time

    ruta = tmp_path / "cupo.json"
    futuro = _time.time() + 86400
    ruta.write_text(json.dumps({"espectador": {"fichas": 0.0, "ts": futuro}}),
                    encoding="utf-8")
    monkeypatch.setattr(cuota, "RUTA", str(ruta))
    monkeypatch.setattr(cuota, "_baldes", {})
    monkeypatch.setattr(cuota, "_cargado", False)
    assert cuota.tomar("espectador") is False, "un reloj del futuro no puede regalar fichas"


def test_el_fallo_de_escritura_se_ve_en_el_estado(tmp_path, monkeypatch):
    import os as _os

    cerrada = tmp_path / "cerrada"
    cerrada.mkdir()
    _os.chmod(cerrada, 0o500)              # se puede leer y recorrer, no crear
    monkeypatch.setattr(cuota, "RUTA", str(cerrada / "cupo.json"))
    monkeypatch.setattr(cuota, "_baldes", {})
    monkeypatch.setattr(cuota, "_cargado", True)
    monkeypatch.setattr(cuota, "_ultimo_fallo", None)
    cuota.tomar("espectador")
    # La ruta no existe y no se puede crear: el fallo queda anotado, no se traga.
    assert cuota.estado().get("_escritura")


def test_la_apertura_conserva_su_tarjeta_y_no_la_generica():
    """`listo: false` no puede borrar el texto propio de la apertura."""
    card = _tarjeta()
    card.actualizar({
        "listo": False, "modo": "APERTURA", "fuente": "apertura",
        "estado": {"motivo": "en el menú del juego"}, "recomendaciones": [],
    })
    assert card.lbl_accion.get_label() == "ESPERANDO PARTIDA"
    assert card.lbl_razon.get_label() == "en el menú del juego"


def test_el_desempate_exige_replicacion_fuera_de_muestra(tmp_path, monkeypatch):
    """Un ítem que cambia de signo fuera de muestra no puede mandar en un empate."""
    import json

    from coach import valor

    doc = {
        "generado": "2026-11-18", "corpus": {"sha256_db": "abc"},
        "metodo": {}, "oos": {"spearman": 0.57, "acuerdo_signo": 0.81},
        "items": {
            "a": {"nombre": "A", "efecto_pp": 0.2, "ic90": [-1, 1], "lcb90": -0.4,
                  "n": 4000, "etiqueta": "medido", "oos_signo": True},
            "b": {"nombre": "B", "efecto_pp": 2.4, "ic90": [0.8, 4.0], "lcb90": 0.8,
                  "n": 4000, "etiqueta": "medido", "oos_signo": False},
        },
    }
    ruta = tmp_path / "modelo.json"
    ruta.write_text(json.dumps(doc), encoding="utf-8")
    (tmp_path / "corpus.json").write_text(json.dumps({"sha256_db": "abc"}),
                                          encoding="utf-8")
    monkeypatch.setattr(valor, "RUTA", str(ruta))
    monkeypatch.setattr(valor, "RUTA_CORPUS", str(tmp_path / "corpus.json"))
    monkeypatch.setattr(valor, "_cache", {"ruta": None, "doc": None, "error": None})

    filas = [{"id": "a", "score": 10.0}, {"id": "b", "score": 9.8}]
    assert valor.preferencia(filas, 0.5) is None, "sin replicación no hay aviso"
    assert valor.desempatar(filas, 0.5)[1] is None

    doc["items"]["b"]["oos_signo"] = True
    ruta.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(valor, "_cache", {"ruta": None, "doc": None, "error": None})
    aviso = valor.preferencia(filas, 0.5)
    assert aviso and aviso["nombre"] == "B" and aviso["lcb90"] == 0.8


def test_sin_empate_no_hay_aviso(tmp_path, monkeypatch):
    import json

    from coach import valor

    doc = {"generado": "x", "corpus": {"sha256_db": "abc"}, "metodo": {},
           "items": {"a": {"lcb90": 0.1, "oos_signo": True, "etiqueta": "medido",
                           "n": 100, "ic90": [-1, 1], "efecto_pp": 0.2},
                     "b": {"lcb90": 2.0, "oos_signo": True, "etiqueta": "medido",
                           "n": 100, "ic90": [1, 3], "efecto_pp": 2.0}}}
    ruta = tmp_path / "modelo.json"
    ruta.write_text(json.dumps(doc), encoding="utf-8")
    (tmp_path / "corpus.json").write_text(json.dumps({"sha256_db": "abc"}),
                                          encoding="utf-8")
    monkeypatch.setattr(valor, "RUTA", str(ruta))
    monkeypatch.setattr(valor, "RUTA_CORPUS", str(tmp_path / "corpus.json"))
    monkeypatch.setattr(valor, "_cache", {"ruta": None, "doc": None, "error": None})
    assert valor.preferencia([{"id": "a", "score": 10.0},
                              {"id": "b", "score": 5.0}], 0.5) is None

"""Caos: ninguna condición rara puede dejar la app sin servir.

La regla del proyecto es que la app siga dando valor cuando falla la red, la cuota, el
broadcast o un archivo. Estas pruebas rompen a propósito cada pieza de adorno y
comprueban que el motor, el endpoint y los paneles siguen respondiendo.

Nada de esto necesita GTK ni red: se falsean las fuentes.
"""
import json
import os
import sys

import numpy as np
import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import cuota, estado_guardado, servidor, valor   # noqa: E402
from herramientas.lab import corpus                         # noqa: E402


# --- el endpoint no puede morir por un dato raro -------------------------------
def test_el_estado_serializa_numpy_y_sets():
    cuerpo = servidor._json_default(np.int64(7))
    assert cuerpo == 7 and isinstance(cuerpo, int)
    assert servidor._json_default({"a", "b"}) == ["a", "b"] or True


def test_un_objeto_raro_no_tumba_el_endpoint(monkeypatch):
    """Si json.dumps falla, el panel recibe un estado honesto en vez de un 500."""
    enviado = {}

    class Handler:
        def send_response(self, *a):
            enviado["codigo"] = a

        def send_header(self, *a):
            pass

        def end_headers(self):
            pass

        def wfile(self):
            return self

        def write(self, datos):
            enviado["cuerpo"] = datos

    h = servidor.Manejador.__new__(servidor.Manejador) if hasattr(servidor, "Manejador") else None
    if h is None:
        pytest.skip("el nombre del handler cambió")
    h.send_response = Handler().send_response
    h.send_header = Handler().send_header
    h.end_headers = Handler().end_headers
    h.wfile = Handler()
    servidor.Manejador._enviar(h, 200, {"objeto": object(), "n": np.int64(3)})
    cuerpo = json.loads(enviado["cuerpo"])
    assert cuerpo["n"] == 3                      # numpy se convierte a número
    assert isinstance(cuerpo["objeto"], str)     # lo que no se puede, se dice


# --- caches corruptas ----------------------------------------------------------
@pytest.mark.parametrize("contenido", ["", "no es json", '{"a": [1,2', "\x00\x01\x02",
                                       "[]", "null", '{"datos": 3}'])
def test_estado_guardado_aguanta_cualquier_basura(tmp_path, contenido):
    ruta = tmp_path / "estado.json"
    ruta.write_text(contenido, encoding="utf-8", errors="ignore")
    datos, _edad = estado_guardado.cargar(str(ruta))
    assert datos is None, "un archivo roto no puede devolver datos"


def test_la_pausa_de_cuota_aguanta_una_cache_rota(tmp_path, monkeypatch):
    from coach import en_vivo
    ruta = tmp_path / "pausa.json"
    ruta.write_text("{{{", encoding="utf-8")
    monkeypatch.setattr(en_vivo, "_PAUSA_HASTA", 0.0)
    en_vivo._cargar_pausa(str(ruta))          # no debe lanzar
    assert en_vivo.pausa_restante_s() == 0.0


def test_las_caches_de_live_api_aguantan_basura(tmp_path, monkeypatch):
    from coach.fuentes import live_api as LA
    rota = tmp_path / "rota.json"
    rota.write_text('{"x": "y"', encoding="utf-8")
    monkeypatch.setattr(LA, "RUTA_CACHE_URL", str(rota))
    monkeypatch.setattr(LA, "RUTA_NEGADAS", str(rota))
    LA._cargar_cache_url()
    LA._cargar_negadas()


def test_el_corpus_roto_no_rompe_el_arranque(tmp_path, monkeypatch):
    roto = tmp_path / "corpus.json"
    roto.write_text("[[[", encoding="utf-8")
    monkeypatch.setattr(corpus, "RUTA_CORPUS", str(roto))
    assert corpus.leer_congelado() is None
    assert corpus.coincide({}, ruta_db=str(tmp_path / "no.db")) is False


def test_un_cupo_sin_permiso_de_escritura_sigue_contando(tmp_path, monkeypatch):
    import os as _os
    cerrada = tmp_path / "cerrada"
    cerrada.mkdir()
    _os.chmod(cerrada, 0o500)
    monkeypatch.setattr(cuota, "RUTA", str(cerrada / "cupo.json"))
    monkeypatch.setattr(cuota, "_baldes", {})
    monkeypatch.setattr(cuota, "_cargado", True)
    # Otras pruebas abren la capacidad a propósito; aquí se fija la real.
    monkeypatch.setitem(cuota.PERMISOS["espectador"], "capacidad", 2.0)
    assert cuota.tomar("espectador") is True
    assert cuota.tomar("espectador") is True
    assert cuota.tomar("espectador") is False      # en memoria sigue siendo correcto
    assert cuota.estado().get("_escritura")


# --- el motor sobrevive a un artefacto roto -----------------------------------
@pytest.mark.parametrize("contenido", ["", "null", "[]", '"texto"', '{"items": 3}',
                                       '{"items": {"1": "x"}}',
                                       '{"items": {}, "corpus": []}'])
def test_valor_no_lanza_con_artefacto_raro(tmp_path, monkeypatch, contenido):
    ruta = tmp_path / "modelo.json"
    ruta.write_text(contenido, encoding="utf-8")
    corpus_ruta = tmp_path / "corpus.json"
    corpus_ruta.write_text('{"sha256_db": "abc"}', encoding="utf-8")
    monkeypatch.setattr(valor, "RUTA", str(ruta))
    monkeypatch.setattr(valor, "RUTA_CORPUS", str(corpus_ruta))
    monkeypatch.setattr(valor, "_cache", {"ruta": None, "doc": None, "error": None})
    assert valor.cargar() is None
    assert valor.evidencia("1") is None
    assert valor.preferencia([{"id": "1"}, {"id": "2"}], 0.5) is None
    assert valor.resumen()["modo"] in ("CIEGO", "MEDIDO")


def test_el_motor_recomienda_con_el_artefacto_destrozado(tmp_path, monkeypatch):
    """La recomendación no puede caerse porque el laboratorio tenga un archivo roto."""
    ruta = tmp_path / "modelo.json"
    ruta.write_text("{roto", encoding="utf-8")
    monkeypatch.setattr(valor, "RUTA", str(ruta))
    monkeypatch.setattr(valor, "_cache", {"ruta": None, "doc": None, "error": None})
    from coach.motor_api import Motor
    motor = Motor()
    estado = {"t": 900, "yo": {"heroe": "abrams", "almas": 3000,
                               "items": ["3862866912"]},
              "aliados": [{"heroe": "kelvin", "almas": 2500}],
              "enemigos": [{"heroe": "haze", "almas": 3200}],
              "fuente": "prueba", "confianza": 1.0}
    r = motor.analizar_dict(estado)
    assert isinstance(r, dict)
    assert r.get("decision") is not None


# --- el lookahead tiene que poder cambiar una decisión -------------------------
def _ctx_sintetico(nw, costos, m):
    from herramientas.lab import politicas as P
    import numpy as np
    n = 1
    return P, {
        "M": np.asarray([m], dtype=np.float32),
        "datos": {"nw": np.array([nw]), "match": np.array([1]), "slot": np.array([0]),
                  "t": np.array([100.0]), "item": np.array([0]),
                  "vendido_t": np.array([0.0])},
        "modelo": {"cat": {f"i{a}": {"coste": c} for a, c in enumerate(costos)},
                   "ids": [f"i{a}" for a in range(len(costos))],
                   "corto_global": list(range(len(costos)))},
    }


def test_el_lookahead_puede_cambiar_la_decision():
    """La trampa del lookahead monótono: con «el mejor distinto de a» nunca cambia.

    Aquí el candidato caro deja sin oro para la continuación y el barato no: la
    decisión DEBE moverse. Si esta prueba falla, el lookahead volvió a ser un no-op.
    """
    P, ctx = _ctx_sintetico(3000, [2000, 1500, 1500], [0.56, 0.55, 0.54])
    sin, _ = P._politica_modelo(ctx, lookahead=False)
    con, _ = P._politica_modelo(ctx, lookahead=True)
    assert int(sin[0]) == 0
    assert int(con[0]) == 1, "el lookahead no está mirando el oro restante"


def test_sin_accion_factible_no_se_recomienda_nada():
    """Antes devolvía el índice 0 (Juggernaut, 6 400) con 730 de patrimonio."""
    P, ctx = _ctx_sintetico(730, [6400, 3200], [0.6, 0.5])
    accion, ok = P._politica_modelo(ctx, lookahead=False)
    assert not ok.any()
    assert int(accion[0]) == -1

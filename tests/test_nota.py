"""La nota de después de la partida: umbrales, demo ausente y un jugador solo.

Todo corre sin red y con datos fake en un directorio temporal:

- una partida que cumple las tres reglas y otra que no cumple ninguna, con el
  formato exacto de la nota (`3 200 al min 15:32 ✗ (referencia 12:00) · ...`);
- el borde del umbral: 12:00 exacto cumple, 12:01 no;
- compró ítems pero ninguno de 3 200: la regla 1 falla, no queda «sin dato»;
- demo ausente (404 o solo caché): la regla 1 queda `None`, el perfil no se
  completa y **no se aplica ninguna tasa histórica**; las muertes y la
  participación sí se miden del metadata;
- un jugador único en el demo: el mapeo `slot_lobby -> entity_index - 1` sigue
  funcionando cuando no hay 12 controladores;
- `--ultima` elige la partida más reciente por `start_time`, no por el orden que
  devuelva el API.

Se escribe en `unittest` (stdlib) porque en esta máquina no hay `pytest`: estas
pruebas tienen que poder correr con `python3 tests/test_nota.py`.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "herramientas", "demos"))

import consulta  # noqa: E402
import nota      # noqa: E402

CUENTA = 424242
SLOT = 3                 # slot de lobby del jugador de la prueba
ENTIDAD = 9              # entidad del demo: slot de evento = 9 - 1 = 8
ITEM_3200 = 334300056    # Stamina Mastery, 3 200 en data/items.json
ITEM_6400 = 339443430    # Frenzy, 6 400
DURACION = 2743          # 45:43, la partida 139556523


def _lote(slot=SLOT):
    """`m_unLobbyPlayerSlot` como u64 little-endian (16 hex)."""
    return int(slot).to_bytes(8, "little").hex()


def _metadata(match=1, cuenta=CUENTA, slot=SLOT, heroe=6, team=0, gane=True,
              dur=DURACION, kills=5, assists=9, muertes=7, items=None,
              winning_team=None):
    return {"match_info": {
        "match_id": match, "duration_s": dur,
        "winning_team": (team if gane else 1 - team) if winning_team is None else winning_team,
        "start_time": 1000, "players": [{
            "account_id": cuenta, "player_slot": slot, "hero_id": heroe,
            "team": team, "kills": kills, "deaths": muertes, "assists": assists,
            "net_worth": 1000,
            "items": items or [],
            "death_details": [{"game_time_s": i * 60} for i in range(muertes)],
            "stats": [],
        }]}}


def _demo(compras=(), slot_evento=ENTIDAD - 1, slot_lobby=SLOT):
    """NDJSON mínimo: un solo `ctrl` (jugador único) y compras `ab`."""
    filas = [{"tag": "ctrl", "t": "0", "a": str(ENTIDAD), "b": "76561198000000000",
              "c": _lote(slot_lobby), "d": "yo"}]
    for tick, item in compras:
        filas.append({"tag": "ab", "t": str(tick), "a": str(slot_evento),
                      "b": str(item), "c": "0", "d": None})
    return "".join(json.dumps(f) + "\n" for f in filas)


def _tick(segundos):
    return int(round(segundos * 64))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nota-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.meta_dir = self.tmp / "meta"
        self.demo_dir = self.tmp / "demo"
        self.meta_dir.mkdir()
        self.demo_dir.mkdir()

    def poner(self, match=1, metadata=None, demo=None):
        (self.meta_dir / f"{match}.json").write_text(
            json.dumps(metadata if metadata is not None else _metadata(match)),
            encoding="utf-8")
        if demo is not None:
            (self.demo_dir / f"{match}__todo.ndjson").write_text(demo, encoding="utf-8")
        return match

    def medir(self, match=1):
        return nota.medir(match, cuenta=CUENTA, meta_dir=self.meta_dir,
                          demo_dir=self.demo_dir, permitir_red=False)


class Reglas(Base):
    def test_umbrales_cumplidos(self):
        match = self.poner(metadata=_metadata(muertes=5, kills=8, assists=12, dur=1800),
                           demo=_demo([(_tick(11 * 60), ITEM_3200)]))
        doc = nota.evaluar(match, self.medir(match)["fila"], cohorte=[])
        texto = doc["nota"].splitlines()[1]
        self.assertEqual(texto,
                         "3 200 al min 11:00 ✓ (referencia 12:00) · 5 muertes ✓ (meta ≤6) · "
                         "0.67 k+a/min ✓ (meta 0.40)")
        self.assertEqual(doc["cumplidas"], 3)
        self.assertTrue(doc["perfil_completo"])
        self.assertEqual([r["cumple"] for r in doc["reglas"]], [True, True, True])

    def test_umbrales_no_cumplidos_coincide_con_el_ejemplo(self):
        # 15:32, 7 muertes y 14 k+a en 45:43 -> los tres números del ejemplo del informe
        match = self.poner(demo=_demo([(_tick(15 * 60 + 32), ITEM_3200)]))
        doc = nota.evaluar(match, self.medir(match)["fila"], cohorte=[])
        texto = doc["nota"].splitlines()[1]
        self.assertEqual(texto,
                         "3 200 al min 15:32 ✗ (referencia 12:00) · tarde = señal de ir corto de oro · "
                         "7 muertes ✗ (meta ≤6) · "
                         "0.31 k+a/min ✗ (meta 0.40)")
        self.assertEqual(doc["cumplidas"], 0)
        self.assertTrue(doc["perfil_completo"])

    def test_el_borde_del_3200_es_el_minuto_12(self):
        justo = self.poner(1, demo=_demo([(_tick(12 * 60), ITEM_3200)]))
        tarde = self.poner(2, metadata=_metadata(2),
                           demo=_demo([(_tick(12 * 60 + 1), ITEM_3200)]))
        self.assertTrue(nota.evaluar(justo, self.medir(justo)["fila"])["reglas"][0]["cumple"])
        self.assertFalse(nota.evaluar(tarde, self.medir(tarde)["fila"])["reglas"][0]["cumple"])

    def test_compro_otros_items_pero_ningun_3200_es_fallo(self):
        match = self.poner(demo=_demo([(_tick(8 * 60), ITEM_6400)]))
        doc = nota.evaluar(match, self.medir(match)["fila"])
        regla = doc["reglas"][0]
        self.assertIs(regla["cumple"], False)
        self.assertIn("sin comprar", regla["texto"])
        self.assertNotIn("demo no disponible", doc["nota"])


class DemoAusente(Base):
    def test_sin_demo_no_inventa_el_3200(self):
        match = self.poner()                      # metadata sí, demo no
        doc = nota.evaluar(match, self.medir(match)["fila"], cohorte=[])
        self.assertIsNone(doc["reglas"][0]["cumple"])
        self.assertIn("sin dato", doc["reglas"][0]["texto"])
        # las otras dos reglas sí salen del metadata y no se pierden
        self.assertIs(doc["reglas"][1]["cumple"], False)
        self.assertIsNotNone(doc["reglas"][2]["valor"])
        self.assertFalse(doc["perfil_completo"])
        self.assertEqual(doc["historico"]["tipo"], "sin_perfil")
        self.assertIn("no se aplica", doc["nota"])
        self.assertNotIn("Histórico: 0", doc["nota"])

    def test_un_404_es_demo_no_disponible_y_no_se_reintenta_en_falso(self):
        match = self.poner()
        original = consulta.una
        llamadas = []

        def falla(*a, **k):
            llamadas.append(a)
            raise consulta.ErrorFatal("HTTP 404 en /v1/matches/demo/query")

        consulta.una = falla
        try:
            medido = nota.medir(match, cuenta=CUENTA, meta_dir=self.meta_dir,
                                demo_dir=self.demo_dir, permitir_red=True,
                                rondas_demo=1, reintentos=0)
        finally:
            consulta.una = original
        self.assertEqual(medido["demo"]["estado"], "no disponible")
        self.assertIn("404", medido["demo"]["detalle"])
        doc = nota.evaluar(match, medido["fila"])
        self.assertIsNone(doc["reglas"][0]["cumple"])
        self.assertEqual(doc["historico"]["tipo"], "sin_perfil")
        self.assertEqual(len(llamadas), 1)         # una ronda, un job: sin spam

    def test_sin_red_y_sin_cache_no_llama(self):
        match = self.poner()
        medido = nota.medir(match, cuenta=CUENTA, meta_dir=self.meta_dir,
                            demo_dir=self.demo_dir, permitir_red=False)
        self.assertEqual(medido["demo"]["estado"], "sin red y sin caché")
        self.assertIsNone(nota.evaluar(match, medido["fila"])["reglas"][0]["cumple"])

    def test_rondas_demo_reintenta_y_para(self):
        """Una partida recién jugada se puede esperar: N rondas, N jobs, sin spam."""
        match = self.poner()
        original_una, original_sleep = consulta.una, nota.time.sleep
        llamadas = []

        def falla(*a, **k):
            llamadas.append(a)
            raise consulta.ErrorFatal("HTTP 404: No demo available for match 1")

        consulta.una = falla
        nota.time.sleep = lambda _s: None          # la espera se prueba, no se sufre
        try:
            medido = nota.medir(match, cuenta=CUENTA, meta_dir=self.meta_dir,
                                demo_dir=self.demo_dir, permitir_red=True,
                                rondas_demo=3, espera_demo=0)
        finally:
            consulta.una = original_una
            nota.time.sleep = original_sleep
        self.assertEqual(medido["demo"]["estado"], "no disponible")
        self.assertEqual(len(llamadas), 3)


class JugadorUnico(Base):
    def test_un_solo_controlador_mapea_igual(self):
        match = self.poner(demo=_demo([(_tick(9 * 60), ITEM_3200)]))
        fila = self.medir(match)["fila"]
        self.assertEqual(fila["slot"], SLOT)
        self.assertEqual(fila["slot_evento"], ENTIDAD - 1)
        self.assertEqual(len(fila["compras"]), 1)
        doc = nota.evaluar(match, fila)
        self.assertIs(doc["reglas"][0]["cumple"], True)

    def test_si_el_slot_no_esta_en_el_demo_no_se_mide(self):
        metadata = _metadata(slot=5)               # el demo solo tiene el slot 3
        match = self.poner(metadata=metadata, demo=_demo([(_tick(600), ITEM_3200)]))
        fila = self.medir(match)["fila"]
        self.assertIn("el slot del metadata no aparece en el demo", fila["no_medible"])
        self.assertIsNone(nota.evaluar(match, fila)["reglas"][0]["cumple"])


class Historico(Base):
    def _fila(self, gane=True, muertes=7, kills=5, assists=9, min3200=15.5):
        match = self.poner(metadata=_metadata(gane=gane, muertes=muertes,
                                             kills=kills, assists=assists),
                           demo=_demo([(_tick(min3200 * 60), ITEM_3200)]))
        return self.medir(match)["fila"]

    def test_la_tasa_del_perfil_sale_de_la_cohorte(self):
        cohorte = [
            {"match": 10, "gane": 1, "min3200": 10.0, "muertes": 5, "participacion": 0.5},
            {"match": 11, "gane": 1, "min3200": 11.0, "muertes": 6, "participacion": 0.6},
            {"match": 12, "gane": 0, "min3200": 9.0, "muertes": 4, "participacion": 0.7},
            {"match": 13, "gane": 1, "min3200": 20.0, "muertes": 9, "participacion": 0.2},
        ]
        doc = nota.evaluar(1, self._fila(gane=False, muertes=5, kills=8, assists=12,
                                        min3200=10.0), cohorte=cohorte)
        self.assertEqual(doc["historico"]["n"], 3)       # perfil 3/3, sin la analizada
        self.assertEqual(doc["historico"]["victorias"], 2)
        self.assertEqual(doc["historico"]["tasa_pct"], 67)
        self.assertIn("3 partidas con ese perfil → 2 victorias (67 %)", doc["nota"])
        self.assertIn("4 partidas de Abrams", doc["nota"])

    def test_excluye_la_partida_analizada_de_su_propia_tasa(self):
        cohorte = [
            {"match": 1, "gane": 1, "min3200": 10.0, "muertes": 5, "participacion": 0.5},
            {"match": 2, "gane": 0, "min3200": 15.0, "muertes": 7, "participacion": 0.3},
        ]
        doc = nota.evaluar(1, self._fila(), cohorte=cohorte)
        self.assertEqual(doc["historico"]["n"], 1)
        self.assertEqual(doc["historico"]["victorias"], 0)
        self.assertTrue(doc["historico"]["sin_esta"])
        self.assertIn("sin esta", doc["nota"])

    def test_sin_perfil_completo_no_aplica_tasa(self):
        match = self.poner()                       # demo ausente
        doc = nota.evaluar(match, self.medir(match)["fila"], cohorte=[
            {"match": 2, "gane": 0, "min3200": 11.0, "muertes": 6, "participacion": 0.6}])
        self.assertEqual(doc["historico"]["tipo"], "sin_perfil")
        self.assertIsNone(doc["historico"]["tasa_pct"])


class Ultima(unittest.TestCase):
    def test_elige_por_start_time_no_por_orden(self):
        partidas = [
            {"match_id": 100, "start_time": 500},
            {"match_id": 200, "start_time": 900},
            {"match_id": 300, "start_time": 700},
        ]
        self.assertEqual(nota.elegir_ultima(partidas)["match_id"], 200)

    def test_historial_sin_red_no_llama(self):
        with self.assertRaises(nota.SinDato):
            nota.historial(CUENTA, permitir_red=False)

    def test_historial_vacio_avisa(self):
        with self.assertRaises(nota.SinDato):
            nota.elegir_ultima([])


class CargaCohorte(unittest.TestCase):
    def test_filtra_abrams_y_lo_incompleto(self):
        tmp = Path(tempfile.mkdtemp(prefix="nota-cohorte-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ruta = tmp / "cohorte.json"
        ruta.write_text(json.dumps({"partidas": [
            {"match": 1, "heroe": 6, "gane": 1, "min3200": 10.0, "muertes": 5,
             "participacion": 0.5},
            {"match": 2, "heroe": 2, "gane": 0, "min3200": 10.0, "muertes": 5,
             "participacion": 0.5},
            {"match": 3, "heroe": 6, "gane": 0, "muertes": 5, "participacion": 0.5},
        ]}), encoding="utf-8")
        cohorte = nota.cargar_cohorte(ruta)
        self.assertEqual([c["match"] for c in cohorte], [1])

    def test_sin_archivo_es_cohorte_vacia(self):
        self.assertEqual(nota.cargar_cohorte("/no/existe/cohorte.json"), [])


class Documento(Base):
    def test_el_json_trae_las_tres_metricas_y_la_nota(self):
        match = self.poner(demo=_demo([(_tick(10 * 60), ITEM_3200)]))
        doc = nota.analizar(match, cuenta=CUENTA, cohorte=[], meta_dir=self.meta_dir,
                            demo_dir=self.demo_dir, permitir_red=False)
        self.assertEqual(doc["metricas"]["min3200"], 10.0)
        self.assertEqual(doc["metricas"]["muertes"], 7)
        self.assertEqual(doc["metricas"]["participacion"], 0.31)
        self.assertEqual(doc["codigo"], 0)
        self.assertIn("Abrams", doc["nota"])
        self.assertEqual(doc["demo"]["estado"], "caché")
        # cabeza, reglas, población y histórico. La población se añadió el 2026-11-18:
        # la cohorte propia (24 partidas) es chica y el dato de 3 538 partidas es el que
        # da contexto real.
        self.assertEqual(len(doc["nota"].splitlines()), 4)
        self.assertIn("Población (3 538 partidas de Abrams)", doc["nota"])
        json.dumps(doc)          # el panel lo tiene que poder serializar




class Min3200DesdeMetadata(unittest.TestCase):
    """El 3 200 se mide con el metadata aunque no haya demo.

    Desde el 2026-11-18 el metadata trae `items[]` con `game_time_s`, así que la regla
    más importante de la nota no depende de que la demo exista (casi nunca existe a
    tiempo). Se marca la fuente para no confundirla con la medición de la demo.
    """

    def test_calcula_desde_items_del_metadata(self):
        import json as _json
        import pathlib
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            meta = {"match_info": {"players": [{
                "account_id": 7, "kills": 3, "assists": 9, "deaths": 4,
                "items": [{"game_time_s": 120, "item_id": 1},
                          {"game_time_s": 730, "item_id": 2}]}]}}
            (pathlib.Path(tmp) / "50.json").write_text(_json.dumps(meta), encoding="utf-8")
            nota._CATALOGO = {1: 800, 2: 3200}
            fila = {"heroe": 6, "duracion_s": 1800, "muertes": 4, "participacion": 0.4}
            out = nota.completar_desde_metadata(fila, 50, tmp, 7)
            self.assertEqual(out["min3200"], 12.17)
            self.assertEqual(out["min3200_fuente"], "metadata")

    def test_no_pisa_el_3200_de_la_demo(self):
        fila = {"heroe": 6, "min3200": 10.0}
        out = nota.completar_desde_metadata(fila, 1, "/no/existe", 7)
        self.assertEqual(out["min3200"], 10.0)


if __name__ == "__main__":
    unittest.main()

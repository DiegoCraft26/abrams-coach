"""El plan de antes de jugar: números reales, sin red y sin inventar.

Se prueban las piezas puras (filtro de temporada, resumen, elección de enfoque y texto)
con historiales falsos, para no depender de la API.
"""
import pathlib
import sys
import unittest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "herramientas" / "demos"))

import plan  # noqa: E402


def partida(mid, ts, res, k, d, a, dur=1800, modo=4, heroe=6):
    return {"match_id": mid, "start_time": ts, "match_mode": modo, "hero_id": heroe,
            "player_match_outcome": res, "player_kills": k, "player_deaths": d,
            "player_assists": a, "match_duration_s": dur}


class TestPlan(unittest.TestCase):
    def test_filtra_temporada_y_modo(self):
        datos = [partida(1, plan.TEMPORADA_2 + 100, 1, 5, 3, 10),
                 partida(2, plan.TEMPORADA_2 - 100, 1, 5, 3, 10),   # temporada anterior
                 partida(3, plan.TEMPORADA_2 + 200, 1, 5, 3, 10, modo=1)]  # no ranked
        out = plan.rankeadas(datos)
        self.assertEqual([x["match_id"] for x in out], [1])

    def test_resumen_cuenta_y_metas(self):
        datos = [partida(1, plan.TEMPORADA_2 + 100, 1, 5, 4, 12),
                 partida(2, plan.TEMPORADA_2 + 200, 2, 4, 9, 6),
                 partida(3, plan.TEMPORADA_2 + 300, 1, 3, 6, 9)]
        r = plan.resumir(plan.rankeadas(datos), {1: 10.0, 3: 13.0})
        self.assertEqual(r["n"], 3)
        self.assertEqual(r["victorias"], 2)
        self.assertEqual(r["muertes_media"], 6.3)
        self.assertEqual(r["part_media"], 0.43)
        self.assertEqual(r["min3200_mediana"], 11.5)
        self.assertEqual(r["min3200_n"], 2)

    def test_enfoque_elige_la_brecha_mayor(self):
        r = {"n": 10, "muertes_media": 9.0, "part_media": 0.55, "min3200_mediana": 11.0}
        clave, texto = plan.enfoque(r)
        self.assertEqual(clave, "muertes")
        self.assertIn("muertes", texto.lower())

    def test_enfoque_mantener_si_todo_cumple(self):
        r = {"n": 10, "muertes_media": 5.0, "part_media": 0.5, "min3200_mediana": 11.0}
        self.assertEqual(plan.enfoque(r)[0], "mantener")

    def test_el_3200_no_se_propone_como_enfoque(self):
        # A escala el corte de 12 min no separa nada: se informa, no se convierte en tarea.
        r = {"n": 10, "muertes_media": 5.0, "part_media": 0.5, "min3200_mediana": 20.0}
        self.assertEqual(plan.enfoque(r)[0], "mantener")

    def test_sin_datos_no_inventa(self):
        r = plan.resumir([], {})
        self.assertEqual(r["n"], 0)
        self.assertIn("no hay plan", plan.texto(r, ("sin datos", "")).lower())

    def test_participacion_minima(self):
        self.assertEqual(plan.participacion(partida(1, 0, 1, 2, 1, 2, dur=600)), 0.4)
        self.assertIsNone(plan.participacion(partida(1, 0, 1, 2, 1, 2, dur=0)))




class TestObjetivo(unittest.TestCase):
    """El objetivo de sesión: una regla, cinco partidas, tres que la cumplan."""

    def _obj(self, regla="muertes", desde=1000.0):
        return plan.crear_objetivo(regla, desde=desde)

    def test_crear_pone_la_meta_de_cada_regla(self):
        self.assertEqual(self._obj("muertes")["meta"], 6)
        self.assertEqual(self._obj("participacion")["meta"], 0.40)
        self.assertEqual(self._obj("min3200")["meta"], 12.0)
        o = self._obj()
        self.assertEqual((o["partidas"], o["necesarias"]), (5, 3))

    def test_cumple_cada_regla(self):
        buena = partida(1, plan.TEMPORADA_2 + 1, 1, 5, 4, 12)
        mala = partida(2, plan.TEMPORADA_2 + 2, 0, 3, 9, 4)
        self.assertTrue(plan.cumple(buena, "muertes", {}))
        self.assertFalse(plan.cumple(mala, "muertes", {}))
        self.assertTrue(plan.cumple(partida(3, plan.TEMPORADA_2, 1, 4, 6, 10), "participacion", {}))
        self.assertFalse(plan.cumple(mala, "participacion", {}))
        self.assertTrue(plan.cumple(buena, "min3200", {1: 11.0}))
        self.assertIsNone(plan.cumple(buena, "min3200", {}))

    def test_progreso_solo_cuenta_despues_del_objetivo(self):
        obj = self._obj(desde=100.0)
        antes = partida(1, 50, 1, 5, 2, 10)      # antes del objetivo
        hechas = [partida(2, 200, 1, 5, 4, 10), partida(3, 300, 0, 5, 9, 10)]
        pr = plan.progreso([antes] + hechas, obj, {})
        self.assertEqual(pr["hechas"], 2)
        self.assertEqual(pr["cumplidas"], 1)

    def test_progreso_no_cuenta_partidas_sin_dato(self):
        obj = self._obj(regla="min3200", desde=0.0)
        pr = plan.progreso([partida(1, 10, 1, 5, 4, 10)], obj, {})
        self.assertEqual(pr["hechas"], 0)

    def test_texto_del_objetivo(self):
        obj = self._obj(desde=0.0)
        pr = {"hechas": 2, "cumplidas": 1, "objetivo_partidas": 5, "necesarias": 3,
              "logrado": False, "agotado": False}
        t = plan.texto_objetivo(obj, pr)
        self.assertIn("3 de 5", t)
        self.assertIn("vas 1/2", t)
        pr.update({"cumplidas": 3, "logrado": True})
        self.assertIn("cumplido", plan.texto_objetivo(obj, pr))
        pr.update({"logrado": False, "agotado": True})
        self.assertIn("cerrada", plan.texto_objetivo(obj, pr))




class TestReferencia(unittest.TestCase):
    def test_banda_por_badge(self):
        self.assertEqual(plan.banda(55), "baja")
        self.assertEqual(plan.banda(61), "media")
        self.assertEqual(plan.banda(86), "alta")
        self.assertIsNone(plan.banda(None))

    def test_referencia_usa_la_ultima_partida_con_badge(self):
        partidas = [partida(2, plan.TEMPORADA_2 + 20, 1, 5, 4, 10),
                    {**partida(1, plan.TEMPORADA_2 + 10, 1, 5, 4, 10), "ranked_display_badge": 55}]
        b, badge = plan.referencia_badges(partidas)
        self.assertEqual((b, badge), ("baja", 55))
        r = plan.resumir(partidas, {})
        t = plan.texto_referencia(partidas, r)
        self.assertIn("banda (baja, badge 55)", t)
        self.assertIn("55.2", t)

    def test_sin_badge_no_pinta_referencia(self):
        partidas = [partida(1, plan.TEMPORADA_2 + 10, 1, 5, 4, 10)]
        self.assertEqual(plan.texto_referencia(partidas, plan.resumir(partidas, {})), "")


if __name__ == "__main__":
    unittest.main()

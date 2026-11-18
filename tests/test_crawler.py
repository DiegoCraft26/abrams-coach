"""Piezas puras del crawler de demos: cola, reanudación y 404. Sin red.

Se fija lo que puede romper una corrida larga sin que nadie mire:

- `alta` no duplica una partida y respeta la edad mínima para pedir la demo;
- `listos` solo devuelve lo que ya toca;
- un 404 se reintenta y solo se da por perdido tras `max_intentos_demo`;
- el estado guardado se puede volver a cargar y lo que quedó `en_curso` vuelve a
  la cola (reanudable de verdad, no de intención);
- las dos consultas son las que se midieron: compras sin filtro y oro tipo 0.

`unittest` de la stdlib: en la PC no hay pytest ni pip.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "herramientas", "demos"))

import crawler  # noqa: E402


def args(**cambios):
    base = {
        "edad_demo_min": 20.0,
        "espera_404_min": 12.0,
        "max_intentos_demo": 3,
        "max_fallos_red": 3,
    }
    base.update(cambios)
    return SimpleNamespace(**base)


def corrida():
    return {"procesadas": 0, "404": 0, "fallidas": 0, "bytes": 0,
            "descubiertas": 0, "segundos_partida": []}


class Alta(unittest.TestCase):
    def test_no_duplica(self):
        estado = crawler.estado_nuevo()
        ahora = time.time()
        self.assertTrue(crawler.alta(estado, 1, "recently-fetched", ahora - 900,
                                     1800, ahora - 100, args()))
        self.assertFalse(crawler.alta(estado, 1, "active", ahora, None, ahora, args()))
        self.assertEqual(len(estado["partidas"]), 1)

    def test_espera_la_maduracion_de_la_demo(self):
        estado = crawler.estado_nuevo()
        ahora = time.time()
        crawler.alta(estado, 1, "active", ahora - 600, None, ahora, args())
        info = estado["partidas"]["1"]
        self.assertAlmostEqual(info["siguiente"], ahora + 20 * 60, delta=2)

    def test_partida_vieja_esta_lista_ya(self):
        estado = crawler.estado_nuevo()
        ahora = time.time()
        crawler.alta(estado, 1, "recently-fetched", ahora - 7200, 3600,
                     ahora - 3600, args())
        self.assertLessEqual(estado["partidas"]["1"]["siguiente"], time.time())


class Listos(unittest.TestCase):
    def test_solo_lo_que_ya_toca(self):
        estado = crawler.estado_nuevo()
        ahora = time.time()
        for mid, siguiente in ((1, ahora - 5), (2, ahora + 500), (3, ahora - 1)):
            estado["partidas"][str(mid)] = {"estado": "espera", "siguiente": siguiente,
                                            "inicio": 0}
        estado["partidas"]["4"] = {"estado": "procesada", "siguiente": 0, "inicio": 0}
        claves = [c for c, _ in crawler.listos(estado, ahora)]
        self.assertEqual(sorted(claves), ["1", "3"])

    def test_ordena_por_siguiente(self):
        estado = crawler.estado_nuevo()
        ahora = time.time()
        estado["partidas"] = {
            "b": {"estado": "espera", "siguiente": ahora - 1, "inicio": 1},
            "a": {"estado": "espera", "siguiente": ahora - 9, "inicio": 2},
        }
        self.assertEqual([c for c, _ in crawler.listos(estado, ahora)], ["a", "b"])

    def test_reintento_va_antes_que_el_backlog(self):
        estado = crawler.estado_nuevo()
        ahora = time.time()
        estado["partidas"] = {
            "nueva": {"estado": "espera", "siguiente": ahora - 100,
                      "inicio": ahora - 600, "intentos_demo": 0},
            "reintento": {"estado": "espera", "siguiente": ahora - 1,
                          "inicio": ahora - 3600, "intentos_demo": 1},
        }
        self.assertEqual([c for c, _ in crawler.listos(estado, ahora)],
                         ["reintento", "nueva"])


class Cola(unittest.TestCase):
    def test_cuenta_solo_lo_que_espera(self):
        estado = crawler.estado_nuevo()
        estado["partidas"] = {
            "a": {"estado": "espera"},
            "b": {"estado": "procesada"},
            "c": {"estado": "espera"},
            "d": {"estado": "404"},
        }
        self.assertEqual(crawler.en_cola(estado), 2)


class Resultados(unittest.TestCase):
    def test_404_reintenta_y_luego_cierra(self):
        estado = crawler.estado_nuevo()
        crawler.alta(estado, 7, "manual", None, None, time.time() - 999, args())
        info = estado["partidas"]["7"]
        c = corrida()
        a = args(max_intentos_demo=2)
        crawler.aplicar_resultado(estado, "7", info,
                                  {"estado": "404", "error": "No demo"}, a, c)
        self.assertEqual(info["estado"], "espera")
        self.assertEqual(info["intentos_demo"], 1)
        self.assertGreater(info["siguiente"], time.time())
        self.assertEqual(c["404"], 0)
        crawler.aplicar_resultado(estado, "7", info,
                                  {"estado": "404", "error": "No demo"}, a, c)
        self.assertEqual(info["estado"], "404")
        self.assertEqual(c["404"], 1)

    def test_procesada_suma_bytes_y_filas(self):
        estado = crawler.estado_nuevo()
        crawler.alta(estado, 9, "manual", None, None, time.time() - 999, args())
        info = estado["partidas"]["9"]
        c = corrida()
        crawler.aplicar_resultado(
            estado, "9", info,
            {"estado": "procesada", "bytes": 1234,
             "filas": {"abilities": 10, "currency_gold": 20}, "segundos": 30.0},
            args(), c)
        self.assertEqual(info["estado"], "procesada")
        self.assertEqual(info["bytes"], 1234)
        self.assertEqual(info["filas"]["currency_gold"], 20)
        self.assertEqual(c["procesadas"], 1)
        self.assertEqual(c["bytes"], 1234)

    def test_fallo_de_red_no_es_404(self):
        estado = crawler.estado_nuevo()
        crawler.alta(estado, 11, "manual", None, None, time.time() - 999, args())
        info = estado["partidas"]["11"]
        c = corrida()
        crawler.aplicar_resultado(estado, "11", info,
                                  {"estado": "red", "error": "timeout"},
                                  args(max_fallos_red=2), c)
        self.assertEqual(info["estado"], "espera")
        self.assertEqual(info["fallos_red"], 1)
        self.assertEqual(c["fallidas"], 0)


class Reanudacion(unittest.TestCase):
    def test_guardar_y_cargar(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "estado.json"
            estado = crawler.estado_nuevo()
            crawler.alta(estado, 5, "active", 1, None, 2, args())
            estado["partidas"]["5"]["estado"] = "procesada"
            crawler.alta(estado, 6, "active", 1, None, 2, args())
            estado["partidas"]["6"]["estado"] = "en_curso"
            crawler.guardar_estado(ruta, estado)
            self.assertTrue(ruta.exists())
            vuelta = crawler.cargar_estado(ruta)
            self.assertEqual(vuelta["partidas"]["5"]["estado"], "procesada")
            self.assertEqual(vuelta["partidas"]["6"]["estado"], "espera")
            self.assertEqual(vuelta["partidas"]["6"]["siguiente"], 0)
            self.assertEqual(vuelta["contadores"]["procesadas"], 1)

    def test_estado_roto_se_respalda(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "estado.json"
            ruta.write_text("{esto no es json", encoding="utf-8")
            estado = crawler.cargar_estado(ruta)
            self.assertEqual(estado["partidas"], {})
            self.assertFalse(ruta.exists())
            self.assertTrue(list(Path(tmp).glob("estado.json.roto-*")))


class Consultas(unittest.TestCase):
    def test_compras_sin_filtro_de_jugador(self):
        sql = crawler.SQL_COMPRAS.lower()
        self.assertIn("abilitieschangedevent", sql)
        self.assertNotIn("where", sql)

    def test_oro_filtra_tipo_0_y_escapa_delta(self):
        self.assertIn("currency_type = 0", crawler.SQL_ORO)
        self.assertIn('"delta"', crawler.SQL_ORO)
        self.assertIn("userid", crawler.SQL_ORO)


if __name__ == "__main__":
    unittest.main()

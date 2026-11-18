"""Las piezas puras del extractor de demos: mapeo de slots, reloj, oro y emparejado.

Lo que se fija aquí, sin red:

- `purchaser_player_slot` es `entity_index − 1`, y el slot del corpus sale de
  `m_unLobbyPlayerSlot` (u64 little-endian), no del slot del evento;
- el reloj de partida descuenta los ticks pausados: sin eso un evento posterior a una
  pausa se lee 33 s tarde;
- el emparejado demo↔corpus es por id en orden, no por ventana de tiempo, porque el
  desfase es justamente lo que se mide;
- el oro se lee como «último `new_value` anterior» y no mezcla tipos de moneda;
- `construir_sql` no rompe con nombres, SQL suelto ni `@archivo`.

Está en `unittest` (stdlib) a propósito: en esta máquina no hay `pip` ni `pytest`, y
estas pruebas tienen que poder correr. `pytest` las recoge igual.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "herramientas", "demos"))

import consulta  # noqa: E402
import piloto    # noqa: E402

LOTE = "\x03" + "\x00" * 7          # slot 3 como lo entrega el servidor


def fila_ab(tick, slot, item, cambio):
    return {"tag": "ab", "t": str(tick), "a": str(slot), "b": str(item),
            "c": str(cambio), "d": None}


def fila_cur(tick, user, tipo, delta, nuevo):
    return {"tag": "cur", "t": str(tick), "a": str(user), "b": str(tipo),
            "c": str(delta), "d": str(nuevo)}


class Mapeo(unittest.TestCase):
    def test_slot_del_evento_es_la_entidad_menos_uno(self):
        filas = [{"tag": "ctrl", "t": "0", "a": "9", "b": "76561199100643248",
                  "c": LOTE, "d": "juan"}, fila_ab(11825, 8, 2829638276, 0)]
        mapa, _, compras, _ = piloto.partir(filas)
        self.assertEqual(mapa[9]["slot_evento"], 8)
        self.assertEqual(mapa[9]["slot_lobby"], 3)
        self.assertEqual(compras[0]["slot"], 8)

    def test_el_slot_del_corpus_no_es_el_slot_del_evento(self):
        filas = [{"tag": "ctrl", "t": "0", "a": "9", "b": "76561199100643248",
                  "c": LOTE, "d": "juan"}]
        mapa, _, _, _ = piloto.partir(filas)
        entidad = next(e for e, m in mapa.items() if m["slot_lobby"] == 3)
        self.assertEqual(entidad, 9)
        self.assertNotEqual(entidad - 1, 3)   # 8 != 3: por eso hacía falta el mapeo

    def test_cuenta_de_steam(self):
        filas = [{"tag": "ctrl", "t": "0", "a": "9", "b": "76561199100643248",
                  "c": LOTE, "d": "juan"}]
        mapa, _, _, _ = piloto.partir(filas)
        self.assertEqual(mapa[9]["cuenta"], 1140377520)

    def test_decodificar_slot_acepta_hex_y_bytes(self):
        self.assertEqual(piloto.decodificar_slot("0300000000000000"), 3)
        self.assertEqual(piloto.decodificar_slot(LOTE), 3)
        self.assertIsNone(piloto.decodificar_slot(None))
        self.assertIsNone(piloto.decodificar_slot("corto"))


class Reloj(unittest.TestCase):
    def test_sin_pausas_es_tick_sobre_64(self):
        self.assertAlmostEqual(consulta.segundos_juego(6400, []), 100.0)

    def test_la_pausa_se_descuenta(self):
        pausas = [(1, 0), (10902, 2127)]
        self.assertAlmostEqual(consulta.segundos_juego(8000, pausas), 125.0)
        despues = consulta.segundos_juego(20000, pausas)
        self.assertAlmostEqual(despues, (20000 - 2127) / 64)
        self.assertLess(despues, 20000 / 64)

    def test_pausas_acumuladas(self):
        pausas = [(1, 0), (27976, 2488), (32441, 4604)]
        self.assertEqual(consulta.ticks_pausados(pausas, 1000), 0)
        self.assertEqual(consulta.ticks_pausados(pausas, 30000), 2488)
        self.assertEqual(consulta.ticks_pausados(pausas, 99999), 4604)

    def test_preambulo_se_resta(self):
        self.assertAlmostEqual(consulta.segundos_juego(6400, [], 0.5), 99.5)


class Emparejado(unittest.TestCase):
    def test_por_id_en_orden_no_por_tiempo(self):
        corpus = [{"t": 151, "id": 10}, {"t": 152, "id": 20}]
        demo = [{"item": 20, "segundos": 185.5}, {"item": 10, "segundos": 184.8}]
        pares = piloto.emparejar(corpus, demo)
        self.assertEqual([(c["id"], d["item"]) for c, d, _ in pares], [(10, 10), (20, 20)])

    def test_no_repite_un_evento(self):
        self.assertEqual(
            len(piloto.emparejar([{"t": 1, "id": 10}, {"t": 2, "id": 10}],
                                 [{"item": 10, "segundos": 1.2}])), 1)

    def test_lo_que_falta_no_se_inventa(self):
        pares = piloto.emparejar([{"t": 1, "id": 10}, {"t": 2, "id": 99}],
                                 [{"item": 10, "segundos": 1.2}])
        self.assertEqual({d["item"] for _, d, _ in pares}, {10})

    def test_desfase_por_mediana_ignora_un_par_loco(self):
        pares = [({"t": 100, "id": 1}, {"segundos": 100.5}, 0.0),
                 ({"t": 200, "id": 2}, {"segundos": 200.4}, 0.0),
                 ({"t": 300, "id": 3}, {"segundos": 900.0}, 0.0)]
        medido = piloto.medir_desfase(pares)
        self.assertAlmostEqual(medido["centro"], 0.5, delta=0.2)
        self.assertTrue(medido["dudosos"])
        self.assertEqual(medido["dentro"], "2/3")


class Oro(unittest.TestCase):
    def test_toma_el_ultimo_valor_anterior(self):
        filas = [fila_cur(640, 8, 0, 50, 650), fila_cur(6400, 8, 0, -800, 879)]
        _, moneda, _, _ = piloto.partir(filas)
        self.assertIsNone(piloto.oro_en(moneda, 8, 0))
        self.assertIsNone(piloto.oro_en(moneda, 8, 639))
        self.assertEqual(piloto.oro_en(moneda, 8, 640), 650)
        self.assertEqual(piloto.oro_en(moneda, 8, 6399), 650)
        self.assertEqual(piloto.oro_en(moneda, 8, 6400), 879)

    def test_no_mezcla_tipos(self):
        filas = [fila_cur(10, 8, 0, 50, 650), fila_cur(10, 8, 2, 1, 1)]
        _, moneda, _, _ = piloto.partir(filas)
        self.assertEqual(piloto.oro_en(moneda, 8, 10, tipo=0), 650)
        self.assertEqual(piloto.oro_en(moneda, 8, 10, tipo=2), 1)

    def test_ignora_a_otros_jugadores(self):
        _, moneda, _, _ = piloto.partir([fila_cur(10, 7, 0, 50, 650)])
        self.assertIsNone(piloto.oro_en(moneda, 8, 10))


class SQL(unittest.TestCase):
    def test_las_reservadas_van_comilladas(self):
        for nombre in ("todo", "compras", "oro", "mapa", "pausas", "oro_minuto", "control"):
            _, sql = consulta.construir_sql(nombre)
            self.assertTrue(sql.strip())
            self.assertNotIn("delta", sql.replace('"delta"', ""), f"{nombre}: delta sin comillar")

    def test_todo_lleva_las_cuatro_ramas(self):
        _, sql = consulta.construir_sql("todo")
        for marca in ("'ab'", "'cur'", "'ctrl'", "'pausa'"):
            self.assertIn(marca, sql)
        self.assertEqual(sql.count("UNION ALL"), 3)

    def test_jugador_filtra_solo_el_oro(self):
        _, sql = consulta.construir_sql("todo", 8)
        self.assertIn("WHERE userid = 8", sql)
        self.assertNotIn("purchaser_player_slot = 8", sql)

    def test_sql_suelto(self):
        nombre, sql = consulta.construir_sql("  SELECT tick FROM AbilitiesChangedEvent LIMIT 1; ")
        self.assertEqual(nombre, "suelta")
        self.assertFalse(sql.endswith(";"))

    def test_consulta_desconocida_avisa(self):
        with self.assertRaises(SystemExit):
            consulta.construir_sql("inventada")

    def test_lista_de_partidas(self):
        self.assertEqual(consulta.lista_matches("1, 2;3"), [1, 2, 3])
        self.assertEqual(consulta.lista_matches(""), [])


class Cache(unittest.TestCase):
    def test_el_filtro_por_jugador_tiene_su_propio_archivo(self):
        tmp = Path(tempfile.mkdtemp())
        self.assertEqual(consulta.ruta_cache(tmp, 132662221, "todo").name,
                         "132662221__todo.ndjson")
        self.assertEqual(consulta.ruta_cache(tmp, 132662221, "todo-slot8").name,
                         "132662221__todo-slot8.ndjson")

    def test_un_resultado_vacio_es_cache_valida(self):
        """`oro_minuto` devuelve 0 filas de verdad: no se puede confundir con un fallo."""
        tmp = Path(tempfile.mkdtemp())
        consulta.ruta_cache(tmp, 1, "oro_minuto").write_text("", encoding="utf-8")
        original = consulta.enviar
        consulta.enviar = lambda *a, **k: self.fail("no debía pedir nada al servidor")
        try:
            resumen = consulta.una(1, "oro_minuto", "SELECT 1", tmp)
        finally:
            consulta.enviar = original
        self.assertTrue(resumen["cacheado"])
        self.assertEqual(resumen["filas"], 0)

    def test_el_ndjson_se_lee_linea_a_linea(self):
        ruta = Path(tempfile.mkdtemp()) / "x.ndjson"
        ruta.write_text('{"a":1}\n{"a":2}\n', encoding="utf-8")
        self.assertEqual([f["a"] for f in piloto.leer_rows(ruta)], [1, 2])


if __name__ == "__main__":
    unittest.main()

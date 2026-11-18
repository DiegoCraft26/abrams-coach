"""Pruebas del normalizador de demos, sin red y con datos fake.

Fija lo que rompe el conjunto de datos si nadie mira:

- el reloj descuenta pausas y no el preámbulo;
- `oro_antes` es el saldo *antes* del cargo del mismo tick, no después;
- el pago se busca en tick±2 y se marca si es ambiguo;
- el inventario conserva un componente consumido en la misma compra;
- el conjunto asequible vacío se representa con 0, no con «todos»;
- `change=5` no toca inventario.

`unittest` de la stdlib: en la PC no hay pytest ni pip.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "herramientas" / "lab"))

import demos_norm as dn  # noqa: E402


CATALOGO = {
    "111": {"id": 111, "nombre": "Barato", "costo": 800, "comprable": True, "slot": "weapon"},
    "222": {"id": 222, "nombre": "Medio", "costo": 1600, "comprable": True, "slot": "vitality"},
    "333": {"id": 333, "nombre": "Componente", "costo": 800, "comprable": True, "slot": "weapon"},
    "444": {"id": 444, "nombre": "Mejora", "costo": 1600, "comprable": True, "slot": "weapon"},
    "555": {"id": 555, "nombre": "No comprable", "costo": 800, "comprable": False, "slot": "spirit"},
}
COMPONENTES = {"444": ["333"]}
COMPRABLES = [k for k, v in CATALOGO.items() if v["comprable"]]

META = {
    "winning_team": 0,
    "duration_s": 600,
    "players": [
        {"account_id": 123, "player_slot": 1, "team": 0, "hero_id": 6},
        {"account_id": 456, "player_slot": 2, "team": 1, "hero_id": 7},
    ],
}
META_ITEMS = {
    "winning_team": 0,
    "duration_s": 600,
    "players": [
        {"account_id": 123, "player_slot": 1, "team": 0, "hero_id": 6,
         "items": [{"item_id": "333", "game_time_s": 10},
                   {"item_id": "444", "game_time_s": 50}]},
        {"account_id": 456, "player_slot": 2, "team": 1, "hero_id": 7,
         "items": [{"item_id": "111", "game_time_s": 20}]},
    ],
}
AUX = {
    "pausas": [[1, 0], [3000, 3200]],
    "mapa": {"0": {"entity_index": 1, "steam_id": dn.STEAM_BASE + 123,
                   "account_id": 123, "lobby": 1, "team": 0}},
}


def _demo(compras=None, oro=None, cambio5=False):
    compras = compras if compras is not None else [
        {"tick": 640, "purchaser_player_slot": 0, "ability_id": 333, "change": 0},
        {"tick": 6400, "purchaser_player_slot": 0, "ability_id": 444, "change": 0},
        {"tick": 6400, "purchaser_player_slot": 0, "ability_id": 333, "change": 2},
    ]
    if cambio5:
        compras.append({"tick": 5000, "purchaser_player_slot": 0,
                        "ability_id": 111, "change": 5})
    oro = oro if oro is not None else [
        {"tick": 100, "userid": 0, "delta": 200, "new_value": 800},
        {"tick": 640, "userid": 0, "delta": -800, "new_value": 0},
        {"tick": 1000, "userid": 0, "delta": 2400, "new_value": 2400},
        {"tick": 6400, "userid": 0, "delta": -800, "new_value": 1600},
    ]
    return compras, oro


class PruebasReloj(unittest.TestCase):
    def test_pausas(self):
        self.assertAlmostEqual(dn.segundos_de_juego(6400, [[1, 0], [3000, 3200]]), 50.0)
        self.assertAlmostEqual(dn.segundos_de_juego(640, [[1, 0]]), 10.0)

    def test_pausa_despues_del_tick_no_aplica(self):
        self.assertAlmostEqual(dn.segundos_de_juego(1000, [[3000, 3200]]), 15.625)

    def test_franjas(self):
        self.assertEqual(dn.franja_de(899.9), 0)
        self.assertEqual(dn.franja_de(900.0), 1)
        self.assertEqual(dn.franja_de(1800.0), 2)


class PruebasOro(unittest.TestCase):
    def test_oro_antes_del_cargo_mismo_tick(self):
        ev = [{"tick": 100, "delta": 25, "new_value": 625},
              {"tick": 3723, "delta": -800, "new_value": 78}]
        ticks = [100, 3723]
        self.assertEqual(dn.oro_antes(ev, ticks, 3723), 878)

    def test_oro_antes_ultimo_previo(self):
        ev = [{"tick": 100, "delta": 25, "new_value": 625}]
        self.assertEqual(dn.oro_antes(ev, [100], 200), 625)

    def test_oro_antes_sin_eventos(self):
        self.assertEqual(dn.oro_antes([], [], 50), 600)

    def test_pago_en_ventana(self):
        ev = [{"tick": 99, "delta": -800, "new_value": 100}]
        self.assertEqual(dn.pago_observado(ev, [99], 100), (800, 1))
        self.assertEqual(dn.pago_observado(ev, [99], 101), (800, 1))
        self.assertEqual(dn.pago_observado(ev, [99], 103), (None, 0))


class PruebasMetadata(unittest.TestCase):
    def test_matcher_sin_mapa_y_tiempos_de_metadata(self):
        compras, oro = _demo()
        filas, _ = dn.normalizar_demo(999, META_ITEMS, compras, oro, CATALOGO,
                                      COMPONENTES, None)
        self.assertEqual(filas[0]["hero_id"], 6)
        self.assertEqual(filas[0]["segundos_fuente"], "metadata")
        self.assertAlmostEqual(filas[0]["segundos"], 10.0)
        self.assertAlmostEqual(filas[1]["segundos"], 50.0)
        self.assertEqual(filas[0]["slot_confianza"], 1)

    def test_alinear_tiempos_no_salta_600s(self):
        compras = [{"ability_id": "333", "tick": 640}]
        self.assertEqual(dn.alinear_tiempos(
            compras, [{"item_id": "333", "game_time_s": 400}]), [None])
        self.assertEqual(dn.alinear_tiempos(
            compras, [{"item_id": "333", "game_time_s": 9}]), [9.0])


class PruebasInventario(unittest.TestCase):
    def _filas(self, cambio5=False):
        compras, oro = _demo(cambio5=cambio5)
        filas, stats = dn.normalizar_demo(999, META, compras, oro, CATALOGO,
                                          COMPONENTES, AUX)
        dn.aplicar_conjunto(filas, CATALOGO, COMPONENTES,
                            dn.medianas_por_item(filas), COMPRABLES)
        return filas, stats

    def test_componente_sigue_en_inventario_al_comprar_la_mejora(self):
        filas, _ = self._filas()
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0]["_inventario"], [])
        self.assertEqual(filas[1]["_inventario"], ["333"])
        self.assertEqual(filas[1]["descuento_componentes"], 800)
        self.assertEqual(filas[1]["pagado"], 800)

    def test_change5_no_toca_inventario(self):
        filas, stats = self._filas(cambio5=True)
        self.assertEqual(stats["change5"], 1)
        self.assertNotIn("111", filas[1]["_inventario"])

    def test_heroe_resultado_y_pausas(self):
        filas, _ = self._filas()
        self.assertEqual(filas[0]["hero_id"], 6)
        self.assertEqual(filas[0]["resultado"], "victoria")
        self.assertEqual(filas[0]["heroes_en_partida"], "6|7")
        self.assertAlmostEqual(filas[1]["segundos"], 50.0)
        self.assertEqual(filas[0]["_pausas_ok"], 1)

    def test_pago_ambiguo(self):
        compras, oro = _demo()
        compras.insert(0, {"tick": 6400, "purchaser_player_slot": 0,
                           "ability_id": 111, "change": 0})
        filas, _ = dn.normalizar_demo(999, META, compras, oro, CATALOGO,
                                      COMPONENTES, AUX)
        ambiguas = [f for f in filas if f["_pago_ambiguo"]]
        self.assertEqual(len(ambiguas), 2)

    def test_sin_pago_queda_nulo(self):
        compras, oro = _demo(oro=[{"tick": 100, "userid": 0, "delta": 200,
                                   "new_value": 800}])
        filas, _ = dn.normalizar_demo(999, META, compras, oro, CATALOGO,
                                      COMPONENTES, AUX)
        self.assertIsNone(filas[0]["pagado"])
        self.assertIsNone(filas[0]["descuento_componentes"])


class PruebasConjunto(unittest.TestCase):
    def test_vacio_con_oro_cero(self):
        self.assertEqual(dn.conjunto_asequible(0, [], CATALOGO, COMPONENTES, 0,
                                               COMPRABLES), [])

    def test_descuenta_componente_propio(self):
        # 444 cuesta 1600; con 333 en mano el efectivo necesario son 800.
        con = {i for i, _ in dn.conjunto_asequible(800, ["333"], CATALOGO,
                                                   COMPONENTES, 0, COMPRABLES)}
        sin = {i for i, _ in dn.conjunto_asequible(800, [], CATALOGO,
                                                   COMPONENTES, 0, COMPRABLES)}
        self.assertIn("444", con)
        self.assertNotIn("444", sin)
        self.assertIn("111", sin)

    def test_mediana_empirica_sin_grafo(self):
        # 222 no tiene grafo; con mediana 800 el neto es 800.
        ids = {i for i, _ in dn.conjunto_asequible(800, [], CATALOGO, COMPONENTES,
                                                   800, COMPRABLES)}
        self.assertIn("222", ids)

    def test_no_comprables_no_entran(self):
        ids = {i for i, _ in dn.conjunto_asequible(9999, [], CATALOGO, COMPONENTES,
                                                   0, COMPRABLES)}
        self.assertNotIn("555", ids)

    def test_end_to_end_conteo(self):
        compras, oro = _demo()
        filas, _ = dn.normalizar_demo(999, META, compras, oro, CATALOGO,
                                      COMPONENTES, AUX)
        dn.aplicar_conjunto(filas, CATALOGO, COMPONENTES,
                            dn.medianas_por_item(filas), COMPRABLES)
        primera, segunda = filas
        self.assertEqual(primera["n_asequibles"], 2)       # 111 y 333
        self.assertEqual(primera["n_alternativas"], 1)
        self.assertEqual(segunda["n_asequibles"], 3)       # 111, 222 y 444
        self.assertEqual(segunda["n_alternativas"], 2)
        self.assertEqual(segunda["comprado_es_max"], 1)


class PruebasCaches(unittest.TestCase):
    def test_decodificar_u64(self):
        self.assertEqual(dn.decodificar_u64("0300000000000000"), 3)
        self.assertEqual(dn.decodificar_u64("12"), 12)

    def test_demos_completas_ignora_incompletas(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            buena = base / "1"
            buena.mkdir()
            for n in ("abilities.ndjson", "currency_gold.ndjson", "meta.json"):
                (buena / n).write_text("{}\n", encoding="utf-8")
            mala = base / "2"
            mala.mkdir()
            (mala / "abilities.ndjson").write_text("", encoding="utf-8")
            self.assertEqual([d.name for d in dn.demos_completas(base)], ["1"])


if __name__ == "__main__":
    unittest.main()

"""Ítems contra composición: la consulta cruza ítem × comp × resultado, con muestra.

Lo que se prueba: que el filtro de composición use los seis enemigos, que un ítem cuente
una vez por partida (aunque se compre dos veces), que la tabla exija muestra y que sin
datos no invente una respuesta.
"""
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import items_comp as IC  # noqa: E402

CATALOGO = {"111": {"id": 111, "nombre": "Uno", "costo": 800},
            "222": {"id": 222, "nombre": "Dos", "costo": 3000}}


def partida(mid, enemigos, gano, items, aliados=(7, 8, 9, 10, 11)):
    jugadores = [{"slot": 0, "team": 0, "hero": 6}]
    jugadores += [{"slot": i + 1, "team": 0, "hero": h} for i, h in enumerate(aliados)]
    jugadores += [{"slot": 6 + i, "team": 1, "hero": h} for i, h in enumerate(enemigos)]
    return {"match_id": mid, "gane": gano, "yo": {"slot": 0, "team": 0, "hero": 6},
            "jugadores": jugadores,
            "items": [[iid, t, 0] for iid, t in items]}


def test_enemigos_de_lee_el_equipo_contrario():
    p = partida(1, (12, 13, 14, 15, 16, 17), True, [])
    assert IC.enemigos_de(p) == (12, 13, 14, 15, 16, 17)


def test_un_item_cuenta_una_vez_por_partida():
    p = partida(1, (12, 13, 14, 15, 16, 17), True,
                [(111, 10), (111, 40), (222, 300)])
    tabla = IC.por_item([p], min_n=1, catalogo=CATALOGO)
    por_id = {f["id"]: f for f in tabla["items"]}
    assert por_id[111]["n"] == 1, "comprarlo dos veces no son dos partidas"
    assert por_id[111]["t_mediana_s"] == 10, "se guarda la primera compra"


def test_la_base_es_de_esa_composicion_no_global():
    partidas = [partida(i, (12, 13, 14, 15, 16, 17), i % 2 == 0, [(111, 10)])
                for i in range(10)]
    partidas += [partida(100 + i, (20, 21, 22, 23, 24, 25), False, [(111, 10)])
                 for i in range(10)]
    tabla = IC.comparar(partidas, [12, 13], min_n=5, catalogo=CATALOGO)
    assert tabla["n_partidas"] == 10
    assert tabla["base"] == 0.5
    assert tabla["base_global"] == 0.25


def test_filtra_por_todos_los_heroes_pedidos():
    partidas = [partida(1, (12, 13, 14, 15, 16, 17), True, [(111, 10)]),
                partida(2, (12, 14, 15, 16, 17, 18), True, [(111, 10)])]
    assert len(IC.filtrar(partidas, [12, 13])) == 1
    assert len(IC.filtrar(partidas, [12])) == 2


def test_sin_muestra_no_hay_filas():
    partidas = [partida(i, (12, 13, 14, 15, 16, 17), True, [(111, 10)]) for i in range(3)]
    tabla = IC.comparar(partidas, [12], min_n=100, catalogo=CATALOGO)
    assert tabla["items"] == [] and tabla["n_partidas"] == 3


def test_ordena_por_cota_inferior_y_no_por_winrate_pelado():
    """Un 60 % con 5 partidas no puede ir delante de un 55 % con 900."""
    partidas = [partida(i, (12, 13, 14, 15, 16, 17), i % 10 != 0, [(111, 10)])
                for i in range(900)]
    partidas += [partida(1000 + i, (12, 13, 14, 15, 16, 17), True, [(222, 300)])
                 for i in range(5)]
    tabla = IC.por_item(partidas, min_n=5, catalogo=CATALOGO)
    assert tabla["items"][0]["id"] == 111


def test_sin_partidas_devuelve_estructura_vacia():
    tabla = IC.por_item([], min_n=1, catalogo=CATALOGO)
    assert tabla == {"n_partidas": 0, "base": 0.0, "items": []}


def test_cargar_ignora_lineas_rotas_y_sin_items(tmp_path):
    buena = partida(1, (12, 13, 14, 15, 16, 17), True, [(111, 10)])
    sin = partida(2, (12, 13, 14, 15, 16, 17), True, [])
    ruta = tmp_path / "abrams-items-x.jsonl.gz"
    import gzip
    with gzip.open(ruta, "wt", encoding="utf-8") as f:
        f.write(json.dumps(buena) + "\n")
        f.write("{roto\n")
        f.write(json.dumps(sin) + "\n")
    cargadas = IC.cargar(str(tmp_path))
    assert len(cargadas) == 1 and cargadas[0]["match_id"] == 1


def test_sugerencias_exigen_que_el_item_coincida_en_varios_enemigos(monkeypatch):
    """Con un solo enemigo que lo compre no basta: se calla."""
    tabla = {
        "76": {"n": 1200, "base": 0.43, "items": [
            {"id": 111, "nombre": "Uno", "n": 500, "wr": 0.50, "lb": 0.46, "t_s": 1600},
            {"id": 222, "nombre": "Dos", "n": 400, "wr": 0.49, "lb": 0.45, "t_s": 1500}]},
        "84": {"n": 900, "base": 0.45, "items": [
            {"id": 111, "nombre": "Uno", "n": 380, "wr": 0.48, "lb": 0.44, "t_s": 1400}]},
        "12": {"n": 800, "base": 0.47, "items": [
            {"id": 333, "nombre": "Tres", "n": 300, "wr": 0.47, "lb": 0.42, "t_s": 900}]},
    }
    monkeypatch.setattr(IC, "tabla_heroes", lambda *a, **k: tabla)
    lista = IC.sugerencias([76, 84, 12], min_heroes=2)
    assert [c["id"] for c in lista] == [111], "solo el que coincide en dos enemigos"
    assert IC.sugerencias([12], min_heroes=2) == []


def test_el_texto_de_sugerencia_lleva_muestra(monkeypatch):
    tabla = {"76": {"n": 1200, "base": 0.43, "items": [
                {"id": 111, "nombre": "Uno", "n": 500, "wr": 0.50, "lb": 0.46, "t_s": 1}]},
             "84": {"n": 900, "base": 0.45, "items": [
                {"id": 111, "nombre": "Uno", "n": 380, "wr": 0.48, "lb": 0.44, "t_s": 1}]}}
    monkeypatch.setattr(IC, "tabla_heroes", lambda *a, **k: tabla)
    texto = IC.texto_sugerencia([76, 84])
    assert "Uno" in texto and "n=500" in texto and "pp" in texto


def test_sin_tabla_no_hay_texto(monkeypatch):
    monkeypatch.setattr(IC, "tabla_heroes", lambda *a, **k: {})
    assert IC.texto_sugerencia([76, 84]) == ""


def test_el_cargador_no_mezcla_heroes(tmp_path):
    """El archivo puede tener varios héroes: cargar() tiene que filtrar por uno."""
    import gzip
    abrams = partida(1, (12, 13, 14, 15, 16, 17), True, [(111, 10)])
    abrams["heroe"] = 6
    haze = partida(2, (12, 13, 14, 15, 16, 17), True, [(222, 300)])
    haze["heroe"] = 13
    with gzip.open(tmp_path / "heroe-6-items-x.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(json.dumps(abrams) + "\n")
    with gzip.open(tmp_path / "heroe-13-items-x.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(json.dumps(haze) + "\n")
    assert [p["match_id"] for p in IC.cargar(str(tmp_path), heroe=6)] == [1]
    assert [p["match_id"] for p in IC.cargar(str(tmp_path), heroe=13)] == [2]
    # Los archivos viejos, sin campo `heroe`, cuentan como Abrams.
    solo = tmp_path / "viejo"
    solo.mkdir()
    with gzip.open(solo / "abrams-items-viejo.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(json.dumps({k: v for k, v in abrams.items() if k != "heroe"}) + "\n")
    assert len(IC.cargar(str(solo), heroe=6)) == 1


def test_el_umbral_no_se_cae_por_ruido_de_coma_flotante(monkeypatch):
    """(0.48-0.45)*100 da 2.9999999999999973: justo en el umbral de 3 pp."""
    tabla = {"76": {"n": 1200, "base": 0.43,
                    "items": [{"id": 111, "nombre": "Uno", "n": 500, "wr": 0.50}]},
             "84": {"n": 900, "base": 0.45,
                    "items": [{"id": 111, "nombre": "Uno", "n": 380, "wr": 0.48}]}}
    monkeypatch.setattr(IC, "tabla_heroes", lambda *a, **k: tabla)
    assert [c["id"] for c in IC.sugerencias([76, 84], min_heroes=2)] == [111]


def test_un_item_que_gana_en_uno_solo_no_se_sugiere(monkeypatch):
    """Con seis enemigos, algo destaca por azar: se exige coincidencia en dos."""
    tabla = {"76": {"n": 1200, "base": 0.40,
                    "items": [{"id": 9, "nombre": "Solo", "n": 900, "wr": 0.55}]},
             "84": {"n": 900, "base": 0.45,
                    "items": [{"id": 9, "nombre": "Solo", "n": 200, "wr": 0.55}]}}
    monkeypatch.setattr(IC, "tabla_heroes", lambda *a, **k: tabla)
    # en 84 no llega a la muestra mínima, así que solo cuenta un héroe
    assert IC.sugerencias([76, 84], min_heroes=2) == []


def test_el_delta_publicado_es_la_media_ponderada(monkeypatch):
    tabla = {"76": {"n": 1200, "base": 0.40,
                    "items": [{"id": 111, "nombre": "Uno", "n": 1000, "wr": 0.50}]},
             "84": {"n": 900, "base": 0.40,
                    "items": [{"id": 111, "nombre": "Uno", "n": 1000, "wr": 0.44}]}}
    monkeypatch.setattr(IC, "tabla_heroes", lambda *a, **k: tabla)
    c = IC.sugerencias([76, 84], min_heroes=2)[0]
    assert abs(c["delta_pp"] - 7.0) < 0.01, c   # (10 pp + 4 pp) / 2

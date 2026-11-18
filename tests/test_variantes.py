"""Variantes de composición: la plantilla completa casi nunca se repite, los pares sí.

El caso real (614 partidas usables de Abrams): 612 composiciones enemigas distintas, solo
2 repetidas. Con el espacio teórico de 5 aliados de 24 y 6 enemigos de 25, esperar que se
repita la plantilla exacta es esperar de más. Pero los pares sí: 874 distintos, mediana 9.

Estas pruebas fijan ese comportamiento para que nadie vuelva a prometer «patrones por
composición» sin muestra.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import variantes as V  # noqa: E402


def partida(mid, aliados, enemigos, gano, dur=1800):
    jugadores = [{"slot": 0, "team": 0, "hero": 6}]
    jugadores += [{"slot": i + 1, "team": 0, "hero": h} for i, h in enumerate(aliados)]
    jugadores += [{"slot": 6 + i, "team": 1, "hero": h} for i, h in enumerate(enemigos)]
    return {"match_id": mid, "duracion_s": dur, "gane": gano,
            "yo": {"slot": 0, "team": 0, "items": []}, "jugadores": jugadores}


def test_normaliza_y_quita_mi_heroe_de_las_listas():
    crudo = [partida(1, [7, 8, 9, 10, 11], [12, 13, 14, 15, 16, 17], True)]
    p = V.cargar_preparado(crudo)
    assert len(p) == 1
    assert 6 not in p[0]["aliados"], "mi héroe no cuenta como aliado"
    assert p[0]["aliados"] == (7, 8, 9, 10, 11)
    assert p[0]["enemigos"] == (12, 13, 14, 15, 16, 17)
    assert p[0]["gano"] is True


def test_descarta_partidas_incompletas():
    entera = partida(1, [7, 8, 9, 10, 11], [12, 13, 14, 15, 16, 17], True)
    corta = partida(2, [7, 8, 9, 10, 11], [12, 13, 14], True)
    sin_heroe = partida(3, [7, 8, 9, 10, 11], [12, 13, 14, 15, 16, 17], True)
    sin_heroe["jugadores"][4]["hero"] = None
    p = V.cargar_preparado([entera, corta, sin_heroe])
    assert [x["match_id"] for x in p] == [1]


def test_los_pares_cuentan_una_vez_por_partida():
    """Un par aparece una vez por partida, aunque el orden de los héroes cambie."""
    crudo = [partida(1, [7, 8, 9, 10, 11], [12, 13, 14, 15, 16, 17], True),
             partida(2, [7, 8, 9, 10, 11], [12, 13, 14, 15, 16, 17], False)]
    ind = V.construir(V.cargar_preparado(crudo), k=2)
    assert ind["enemigos"][(12, 13)] == [2, 1]
    assert ind["partidas"] == 2 and ind["victorias"] == 1


def test_la_plantilla_completa_no_se_confunde_con_los_pares():
    crudo = [partida(i, [7, 8, 9, 10, 11],
                     [12, 13, 14, 15, 16, 17 + i], True) for i in range(3)]
    partidas = V.cargar_preparado(crudo)
    comps = V.construir(partidas, k=6)
    assert len(comps["enemigos"]) == 3, "tres plantillas distintas"
    pares = V.construir(partidas, k=2)
    assert len(pares["enemigos"]) > 3


def test_consultar_sin_muestra_devuelve_vacio():
    crudo = [partida(1, [7, 8, 9, 10, 11], [12, 13, 14, 15, 16, 17], True)]
    ind = V.construir(V.cargar_preparado(crudo), k=2)
    assert V.consultar(ind, enemigos=[12], min_n=5)["enemigos"] == []
    assert V.consultar(ind, enemigos=[12], min_n=1)["enemigos"]


def test_wilson_castiga_la_muestra_corta():
    assert V.wilson(5, 0) < V.wilson(50, 0)
    assert V.wilson(0, 0) == 0.0


def test_el_resumen_dice_que_la_plantilla_no_se_repite():
    crudo = [partida(i, [7, 8, 9, 10, 11],
                     [12, 13, 14, 15, 16, 17 + i], bool(i % 2)) for i in range(10)]
    partidas = V.cargar_preparado(crudo)
    r = V.resumen(partidas, V.construir(partidas, k=2))
    assert r["partidas"] == 10
    assert r["comps_enemigas_distintas"] == 10
    assert r["comps_repetidas"] == 0


def test_el_banco_real_es_legible_y_coherente():
    """Guarda de forma: si el cache cambia de esquema, esto falla antes que el panel.

    En un clon limpio se usa la muestra versionada (60 partidas), así que el mínimo se
    ajusta a lo que haya; lo que se comprueba es la forma, no el tamaño.
    """
    partidas = V.cargar()
    minimo = 50 if (V.fuente_banco() or "").endswith("muestra.json") else 500
    assert len(partidas) >= minimo, f"solo {len(partidas)} partidas usables"
    assert all(len(p["aliados"]) == 5 and len(p["enemigos"]) == 6 for p in partidas)
    assert any(p["gano"] for p in partidas) and any(not p["gano"] for p in partidas)


def test_el_archivo_se_filtra_por_heroe(tmp_path):
    """El archivo tiene varios héroes: cargar_archivo(heroe=6) no puede traer a Haze.

    Visto el 2026-11-15: al añadir timelines de Haze, el «banco» pasó de 166k a 179k
    partidas sin que nadie hubiera jugado nada.
    """
    import gzip
    import json as js

    def linea(mid, heroe):
        return js.dumps({"match_id": mid, "heroe": heroe, "gane": True,
                         "yo": {"slot": 0, "team": 0, "hero": heroe},
                         "jugadores": [{"slot": 0, "team": 0, "hero": heroe},
                                       {"slot": 1, "team": 0, "hero": 7},
                                       {"slot": 2, "team": 0, "hero": 8},
                                       {"slot": 3, "team": 0, "hero": 9},
                                       {"slot": 4, "team": 0, "hero": 10},
                                       {"slot": 5, "team": 0, "hero": 11},
                                       {"slot": 6, "team": 1, "hero": 12},
                                       {"slot": 7, "team": 1, "hero": 13},
                                       {"slot": 8, "team": 1, "hero": 14},
                                       {"slot": 9, "team": 1, "hero": 15},
                                       {"slot": 10, "team": 1, "hero": 16},
                                       {"slot": 11, "team": 1, "hero": 17}]})

    with gzip.open(tmp_path / "heroe-6-items-x.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(linea(1, 6) + "\n")
    with gzip.open(tmp_path / "heroe-13-items-y.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(linea(2, 13) + "\n")
    assert [p["match_id"] for p in V.cargar_archivo(str(tmp_path), heroe=6)] == [1]
    assert [p["match_id"] for p in V.cargar_archivo(str(tmp_path), heroe=13)] == [2]

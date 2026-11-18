"""El resumen de la sesión: lee notas archivadas y dice qué regla se fue.

Sin notas no inventa; con notas cuenta partidas, victorias y cumplimiento por regla; y
elige el foco por el peor cumplimiento relativo, no por el primero de la lista.
"""
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas" / "demos"))

import sesion  # noqa: E402


def nota(mid, gane, muertes, part, min3200=None, cumple=None):
    reglas = []
    if min3200 is not None:
        reglas.append({"clave": "min3200", "cumple": min3200 <= 12.0, "valor": min3200})
    reglas.append({"clave": "muertes", "cumple": muertes <= 6, "valor": muertes})
    reglas.append({"clave": "participacion", "cumple": part >= 0.4, "valor": part})
    return {"match_id": mid, "gane": gane,
            "metricas": {"muertes": muertes, "participacion": part, "min3200": min3200},
            "reglas": reglas}


def escribir(tmp_path, docs):
    for doc in docs:
        (tmp_path / f"{doc['match_id']}.json").write_text(
            json.dumps(doc), encoding="utf-8")
    return tmp_path


def test_sin_notas_no_inventa(tmp_path):
    r = sesion.resumir(sesion.cargar(tmp_path, None))
    assert r["n"] == 0
    assert "Sin notas" in sesion.texto(r, None)


def test_resumen_cuenta_y_elige_foco(tmp_path):
    escribir(tmp_path, [
        nota(1, True, 4, 0.6, 10.0),
        nota(2, False, 9, 0.2, 15.0),
        nota(3, False, 8, 0.3, 14.0),
    ])
    r = sesion.resumir(sesion.cargar(tmp_path, None))
    assert r["n"] == 3 and r["victorias"] == 1 and r["derrotas"] == 2
    assert r["muertes_media"] == 7.0
    assert r["por_regla"]["muertes"] == {"evaluadas": 3, "cumplidas": 1}
    f = sesion.foco(r)
    assert f is not None
    # muertes 1/3 y participación 1/3: empate → el primero de las reglas con efecto.
    # El 3 200 (1/3 también) queda fuera del foco a propósito.
    assert "3 200" not in f[0]
    assert "muertes" in f[0] or "k+a/min" in f[0]


def test_sin_foco_si_todo_cumple():
    r = sesion.resumir([nota(1, True, 4, 0.6, 9.0), nota(2, True, 5, 0.7, 10.0)])
    assert sesion.foco(r) is None


def test_filtro_por_tiempo(tmp_path):
    escribir(tmp_path, [nota(1, True, 4, 0.6)])
    import os, time
    viejo = time.time() - 72 * 3600
    os.utime(tmp_path / "1.json", (viejo, viejo))
    assert sesion.cargar(tmp_path, 24) == []
    assert len(sesion.cargar(tmp_path, None)) == 1


def test_el_foco_ignora_el_3200():
    """El 3 200 se informa, pero no se propone como tarea: no tiene efecto demostrado."""
    r = sesion.resumir([nota(1, False, 4, 0.9, 30.0), nota(2, False, 4, 0.9, 28.0)])
    f = sesion.foco(r)
    assert f is None, "con muertes y participación cumplidas no hay foco, aunque el 3200 falle"
    assert "3 200" in sesion.texto(r, None)      # sí se informa

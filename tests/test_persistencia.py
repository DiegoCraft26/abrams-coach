"""Pruebas de la capa de persistencia SQLite.

Ejecutable como script (`python3 tests/test_persistencia.py`) y como pytest.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from coach.persistencia import (
    conectar,
    guardar_resultado,
    migrar,
    resumen_partida,
    ultimas_partidas,
    winrate_por_primer_item,
)
from coach.persistencia.repos import Resultado
from herramientas.archivar import archivar

FALLOS: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    if condicion:
        print(f"  ok   {nombre}")
    else:
        print(f"  FALLA {nombre}  {detalle}")
        FALLOS.append(nombre)


def _escribir_jsonl(ruta: Path, filas: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as archivo:
        for fila in filas:
            archivo.write(json.dumps(fila, ensure_ascii=False) + "\n")


def _preparar_entrada(base: Path) -> Path:
    salida = base / "salida"
    grabaciones = base / "grabaciones"
    salida.mkdir(parents=True, exist_ok=True)
    grabaciones.mkdir(parents=True, exist_ok=True)
    _escribir_jsonl(
        salida / "decisiones.jsonl",
        [
            {
                "ts": 1000.1,
                "t": 120.0,
                "match_id": 42,
                "almas": 3000,
                "oro": 2500,
                "estado": "INICIO",
                "recomendaciones": [
                    {"id": "melee", "nombre": "Melee Lifesteal", "costo": 500, "razones": ["sustain", "barato"]},
                    {"id": "close", "nombre": "Close Quarters", "costo": 1250, "razones": ["pelea"]},
                ],
                "ms": 4.0,
                "fuente": "test",
            }
        ],
    )
    _escribir_jsonl(
        salida / "monitor-42.jsonl",
        [
            {
                "ts": 1005.0,
                "t": 125.0,
                "match": 42,
                "almas": 3100,
                "oro": 2600,
                "estado": "FARM",
                "delta": -10.0,
                "recs": [["Mystic Shot", 1600, True, "daño"], ["Trophy Collector", 1600, False, None]],
            }
        ],
    )
    # Formato realista sin match_id explícito: el match sale del nombre monitor-777.jsonl.
    _escribir_jsonl(
        salida / "monitor-777.jsonl",
        [{"ts": 2000.0, "t": 50.0, "almas": 500, "oro": 500, "estado": "INICIO", "recs": []}],
    )
    (grabaciones / "partida-42.mp4").write_bytes(b"video-falso")
    return salida


def _contar(conexion, tabla: str, match_id: int | None = None) -> int:
    if match_id is None:
        fila = conexion.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()
    else:
        fila = conexion.execute(
            f"SELECT COUNT(*) FROM {tabla} WHERE match_id = ?", (match_id,)
        ).fetchone()
    return int(fila[0])


def main() -> int:
    FALLOS.clear()
    with tempfile.TemporaryDirectory(prefix="abrams-persist-") as tmp:
        base = Path(tmp)
        db = base / "prueba.db"
        salida = _preparar_entrada(base)

        r1 = archivar(str(db), salida)
        nuevas1 = r1["nuevas"]
        check("primera pasada importa muestras", nuevas1["muestras"] > 0, str(nuevas1))
        check("primera pasada importa recomendaciones", nuevas1["recomendaciones"] > 0, str(nuevas1))
        check("primera pasada importa videos", nuevas1["videos"] == 1, str(nuevas1))
        check("detecta filas sin match_id", r1["sin_match_id"].get("monitor", 0) >= 0, str(r1["sin_match_id"]))

        r2 = archivar(str(db), salida)
        nuevas2 = r2["nuevas"]
        check("segunda pasada: 0 partidas nuevas", nuevas2["partidas"] == 0, str(nuevas2))
        check("segunda pasada: 0 muestras nuevas", nuevas2["muestras"] == 0, str(nuevas2))
        check("segunda pasada: 0 recomendaciones nuevas", nuevas2["recomendaciones"] == 0, str(nuevas2))
        check("segunda pasada: 0 compras nuevas", nuevas2["compras"] == 0, str(nuevas2))
        check("segunda pasada: 0 videos nuevos", nuevas2["videos"] == 0, str(nuevas2))

        conexion = conectar(db)
        try:
            migrar(conexion)
            check("muestras match 42", _contar(conexion, "muestras", 42) == 2)
            check("recomendaciones match 42", _contar(conexion, "recomendaciones", 42) == 4)
            check("video registrado", _contar(conexion, "videos") == 1)
            check("match 777 desde nombre monitor", _contar(conexion, "muestras", 777) == 1)

            resumen = resumen_partida(conexion, 42)
            check("resumen trae match_id", resumen["match_id"] == 42)
            check("resumen cuenta muestras", resumen["muestras"]["n"] == 2, str(resumen["muestras"]))
            check("resumen cuenta recomendaciones", resumen["recomendaciones"] == 4, str(resumen["recomendaciones"]))
            check("resumen trae video", len(resumen["videos"]) == 1, str(resumen["videos"]))

            ultimas = ultimas_partidas(conexion, 5)
            check("ultimas_partidas devuelve lista", isinstance(ultimas, list) and len(ultimas) >= 1)

            guardar_resultado(conexion, Resultado(match_id=42, win=1, fuente="test"))
            conexion.commit()
            winrate = winrate_por_primer_item(conexion)
            check("winrate_por_primer_item devuelve filas", len(winrate) >= 1, str(winrate))
            fila42 = [f for f in winrate if f["partidas"] >= 1]
            check("winrate calcula winrate", any("winrate" in f for f in fila42), str(winrate))

            # Verificación CLI: segunda ejecución debe reportar 0 filas nuevas.
            proc = subprocess.run(
                [sys.executable, str(RAIZ / "herramientas" / "archivar.py"), "--db", str(db), "--salida", str(salida)],
                capture_output=True,
                text=True,
                cwd=str(RAIZ),
                check=False,
            )
            salida_cli = proc.stdout + proc.stderr
            check("CLI exit 0", proc.returncode == 0, salida_cli)
            check("CLI reporta 0 muestras nuevas", "muestras: 0 filas nuevas" in salida_cli, salida_cli)
        finally:
            conexion.close()

    print()
    if FALLOS:
        print(f"{len(FALLOS)} FALLAS: {FALLOS}")
        return len(FALLOS)
    print("todo bien")
    return 0


def test_suite():
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())

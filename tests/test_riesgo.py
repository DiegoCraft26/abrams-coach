"""Aviso de riesgo en vivo: perfil histórico, no predicción.

Lo que se fija aquí, de la regla validada en 3 538 partidas
(`informes/lab/REGLAS-VALIDADAS-2026-11-18.md`):

  1. el motor devuelve `riesgo` **solo** cuando la partida lo sostiene: KDA leído,
     reloj ≥5 min y datos de ahora; si no, `None` y no se pinta nada;
  2. los dos cortes se calculan con sus metas (≤6 muertes, ≥0.40 k+a/min) y el
     contexto viaja con su n;
  3. el aviso vive en la cabecera del panel web, se enciende solo cuando alguno de
     los dos cortes se cruza y no entra en la tarjeta ni en el overlay;
  4. el servidor apaga el campo cuando el payload ya es rancio.

Sin dependencias: `pytest -q tests/test_riesgo.py` (y `python3 tests/test_riesgo.py`).
"""
import json
import os
import shutil
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import motor, servidor                      # noqa: E402
from coach.motor_api import Motor                      # noqa: E402
from coach.ui.web import PAGINA                        # noqa: E402

MOTOR = Motor()

CONTEXTO = "≤6 muertes: 76.9 % vs 36.2 % · ≥0.40: 70.9 % vs 12.8 % (n=3 538)"
MARCA_INI = "// --- chip de riesgo (inicio) ---"
MARCA_FIN = "// --- chip de riesgo (fin) ---"
CAMPOS = {"muertes", "participacion", "muertes_meta", "part_meta", "cruza_muertes",
          "bajo_participacion", "contexto"}


def _estado(t=900, kda=(3, 2, 5), fuente="en_vivo", **extra):
    """Estado con forma de broadcast: `kda=(bajas, muertes, asistencias)`."""
    yo = {"heroe": "Abrams", "almas": 9000, "items": []}
    if kda is not None:
        yo.update({"bajas": kda[0], "muertes": kda[1], "asistencias": kda[2]})
    d = {"t": t, "yo": yo,
         "aliados": [{"heroe": "kelvin", "almas": 8800}],
         "enemigos": [{"heroe": "haze", "almas": 9100},
                      {"heroe": "lash", "almas": 8900}],
         "confianza": 1.0, "fuente": fuente}
    d.update(extra)
    return d


# --- 1. cuándo NO hay perfil ---------------------------------------------------
def test_sin_kda_no_hay_perfil():
    """La pantalla y el OCR no traen bajas/muertes/asistencias: no se inventa nada."""
    sin_kda = MOTOR.analizar_dict(_estado(kda=None))
    assert sin_kda["riesgo"] is None, sin_kda["riesgo"]

    # Modo pantalla publica ceros de relleno (`nucleo_vivo.publicar_pantalla`): un
    # 0/0/0 no es una lectura, y el perfil tiene que quedarse callado.
    ceros = MOTOR.analizar_dict(_estado(kda=(0, 0, 0), fuente="pantalla"))
    assert ceros["riesgo"] is None, ceros["riesgo"]

    # El OCR ni siquiera manda las claves.
    ocr = MOTOR.analizar_dict({"t": 900, "yo": {"heroe": "Abrams", "almas": 9000},
                               "aliados": [], "enemigos": [], "fuente": "ocr"})
    assert ocr["riesgo"] is None, ocr["riesgo"]


def test_antes_de_cinco_minutos_no_hay_perfil():
    """A los 2 min una sola pelea dispara la participación: el corte no informa."""
    assert MOTOR.analizar_dict(_estado(t=299, kda=(5, 7, 3)))["riesgo"] is None
    justo = MOTOR.analizar_dict(_estado(t=300, kda=(3, 2, 5)))["riesgo"]
    assert justo is not None and justo["participacion"] == 1.6, justo


def test_datos_viejos_apagan_el_perfil():
    """El aviso es de la partida que se está jugando, no de una foto de hace 30 s."""
    assert MOTOR.analizar_dict(_estado(rancio=True))["riesgo"] is None
    assert MOTOR.analizar_dict(_estado(edad_s=30))["riesgo"] is None
    fresco = MOTOR.analizar_dict(_estado(edad_s=0.4))
    assert fresco["riesgo"] is not None, fresco.get("riesgo")

    # El umbral de rancio del motor es el mismo que el del servidor: dos números
    # distintos aquí serían dos verdades sobre cuándo un dato deja de ser vivo.
    assert motor.EDAD_RANCIO_S == servidor.UMBRAL_RANCIO_S


# --- 2. qué dice cuando sí lo hay ---------------------------------------------
def test_cruza_el_umbral_de_muertes():
    """7 muertes a los 15 min: cruza la meta de 6 y el aviso lo dice con su número."""
    r = MOTOR.analizar_dict(_estado(t=900, kda=(3, 7, 5)))["riesgo"]
    assert set(r) == CAMPOS, sorted(set(r))
    assert r["muertes"] == 7
    assert r["muertes_meta"] == 6 and r["part_meta"] == 0.40
    # (3+5)/15 = 0.533
    assert r["participacion"] == 0.53, r["participacion"]
    assert r["cruza_muertes"] is True
    assert r["bajo_participacion"] is False
    assert r["contexto"] == CONTEXTO
    # Descriptivo, no pronóstico: no se promete nada sobre el resultado.
    for prohibido in ("ganar", "perder", "predice", "probabilidad"):
        assert prohibido not in r["contexto"].lower(), prohibido


def test_baja_participacion():
    """2 bajas + 1 asistencia en 15 min = 0.20: el otro corte es el que avisa."""
    r = MOTOR.analizar_dict(_estado(t=900, kda=(1, 3, 1)))["riesgo"]
    assert r["muertes"] == 3 and r["cruza_muertes"] is False
    assert r["participacion"] == 0.13, r["participacion"]
    assert r["bajo_participacion"] is True


def test_las_metas_no_se_cruzan_por_igualar():
    """La meta es un corte: 6 muertes justas y 0.40 exacto no son «fuera de meta»."""
    justo = MOTOR.analizar_dict(_estado(t=900, kda=(2, 6, 4)))["riesgo"]
    assert justo["muertes"] == 6 and justo["cruza_muertes"] is False
    assert justo["participacion"] == 0.40 and justo["bajo_participacion"] is False


def test_el_contexto_lleva_el_n_y_las_dos_reglas():
    """Sin n y sin fuente, el número es una afirmación que no se puede sostener."""
    r = MOTOR.analizar_dict(_estado())["riesgo"]
    assert "3 538" in r["contexto"]
    for cifra in ("76.9", "36.2", "70.9", "12.8"):
        assert cifra in r["contexto"], cifra


# --- 3. dónde se ve: cabecera del panel web, y solo ahí ------------------------
def test_el_chip_vive_en_la_cabecera():
    """Siete zonas cerradas: el aviso usa la cabecera, no añade una zona."""
    cabecera = PAGINA.split("<body>", 1)[1].split("</header>", 1)[0]
    assert 'id="riesgo"' in cabecera
    assert PAGINA.count('id="riesgo"') == 1
    assert 'id="riesgo"' not in PAGINA.split("<main>", 1)[1]
    # Entra apagado: sin `riesgo` en el payload no se ve nada.
    assert 'id="riesgo" class="chip oculto"' in PAGINA


def test_el_aviso_no_entra_en_la_tarjeta_ni_en_el_overlay():
    """Ahí manda la regla de solo dos cosas (ítem + camino)."""
    for ruta in (("coach", "ui", "tarjeta.py"), ("herramientas", "overlay.py")):
        with open(os.path.join(RAIZ, *ruta), encoding="utf-8") as f:
            fuente = f.read()
        assert "riesgo" not in fuente, ruta


def _chip_js():
    assert MARCA_INI in PAGINA and MARCA_FIN in PAGINA
    return PAGINA.split(MARCA_INI, 1)[1].split(MARCA_FIN, 1)[0]


def _nodo():
    return shutil.which("node") or next(
        (ruta for ruta in (os.path.expanduser("~/.local/bin/node"), "/usr/bin/node")
         if os.path.exists(ruta)), None)


def test_el_chip_solo_se_enciende_cuando_toca():
    """Se ejecuta el JS real del panel (node); si no hay node, se fija la condición."""
    casos = [
        {"muertes": 7, "participacion": 0.53, "muertes_meta": 6, "part_meta": 0.4,
         "cruza_muertes": True, "bajo_participacion": False, "contexto": CONTEXTO},
        {"muertes": 11, "participacion": 0.6, "muertes_meta": 6, "part_meta": 0.4,
         "cruza_muertes": True, "bajo_participacion": False, "contexto": CONTEXTO},
        {"muertes": 2, "participacion": 0.31, "muertes_meta": 6, "part_meta": 0.4,
         "cruza_muertes": False, "bajo_participacion": True, "contexto": CONTEXTO},
        # Dentro de las dos metas: no hay nada que decir.
        {"muertes": 3, "participacion": 0.55, "muertes_meta": 6, "part_meta": 0.4,
         "cruza_muertes": False, "bajo_participacion": False, "contexto": CONTEXTO},
        None,
    ]
    nodo = _nodo()
    if nodo is None:                      # sin node no se finge: se fija la condición
        assert "r.cruza_muertes || r.bajo_participacion" in PAGINA
        return
    js = _chip_js() + "\nprocess.stdout.write(JSON.stringify(" \
        "JSON.parse(process.argv[1]).map(chipRiesgo)));\n"
    salida = subprocess.run([nodo, "-e", js, json.dumps(casos)],
                            capture_output=True, text=True, timeout=30)
    assert salida.returncode == 0, salida.stderr
    muertes, once, participacion, dentro, nada = json.loads(salida.stdout)

    assert muertes["texto"] == "7 muertes · meta ≤6", muertes
    assert muertes["clase"] == "riesgo", muertes          # ámbar
    assert muertes["title"] == CONTEXTO

    assert once["texto"] == "11 muertes · meta ≤6", once
    assert once["clase"] == "riesgo alto", once           # rojo: ya no se endereza

    assert participacion["texto"] == "0.31 k+a/min · meta 0.40", participacion
    assert participacion["clase"] == "riesgo", participacion

    assert dentro is None and nada is None


# --- 4. el payload servido no repite un aviso de hace medio minuto ------------
def test_el_servidor_apaga_el_riesgo_cuando_el_payload_es_rancio():
    perfil = {"muertes": 7, "cruza_muertes": True}
    fresco = servidor.estado_publico({"riesgo": perfil}, 0.5)
    assert fresco["rancio"] is False and fresco["riesgo"] == perfil
    viejo = servidor.estado_publico({"riesgo": perfil}, 30.0)
    assert viejo["rancio"] is True and viejo["riesgo"] is None
    # No se destruye el resto de la foto: el panel sigue diciendo qué comprar.
    assert servidor.estado_publico({"riesgo": perfil, "t": 900}, 30.0)["t"] == 900

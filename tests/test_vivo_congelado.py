"""Con un tick que no avanza, el estado NO debe republicarse como si fuera fresco.

Regresión del 2026-11-07: el guard avisaba una vez y al segundo siguiente volvía a
publicar el estado congelado, con lo que la marca de tiempo se refrescaba y `rancio`
nunca se ponía en True. El panel quedaba diciendo "en vivo" con el reloj y las almas
parados indefinidamente (stream cortado o partida terminada).

Se prueba en un SUBPROCESO a propósito: `bucle_vivo` es un bucle infinito y arrancarlo
dentro del mismo proceso deja hilos vivos que a veces demoran la salida del test cuando
corre en lote.
"""
import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HIJO = r"""
import json, sys, threading, time
sys.path.insert(0, %r)
import run as R
from coach import en_vivo as EV
from coach import servidor as S

class EscuchaFalsa:
    def __init__(self, *a, **k):
        def jugador(c, e, h, al):
            return {"cuenta": c, "equipo": e, "heroe": h, "almas": al,
                    "neto": al + 300, "bajas": 1, "muertes": 0, "asistencias": 2}
        self.estado = {"tick": 9492, "t": 148.3,
                       "jugadores": [jugador(1, 2, "Abrams", 900), jugador(2, 3, "Haze", 800)],
                       "yo": jugador(1, 2, "Abrams", 900),
                       "aliados": [jugador(1, 2, "Abrams", 900)],
                       "enemigos": [jugador(2, 3, "Haze", 800)]}
        self.error = None
        self.filas = 0
    def arrancar(self): return self
    def parar(self, espera=1.0): return self
    def vivo(self): return True

class Args:
    match = None
    cuenta = 1
    intervalo = 1.0

EV.partida_activa = lambda cuenta, timeout=20, unico=False: 111
EV.Escucha = EscuchaFalsa
threading.Thread(target=R.bucle_vivo, args=(Args(), lambda d: {
    "t": d["t"], "almas": d["yo"].get("almas"), "listo": True, "fuente": "en_vivo"}),
    daemon=True).start()

time.sleep(2.5)
_, _, edad1 = S.EST.encuesta()
time.sleep(8.0)
_, _, edad2 = S.EST.encuesta()
print(json.dumps({"edad1": edad1, "edad2": edad2, "umbral": S.UMBRAL_RANCIO_S}))
sys.stdout.flush()
import os as _os
_os._exit(0)
""" % RAIZ

HECHOS = {}


def probar(nombre, condicion, detalle=""):
    HECHOS[nombre] = bool(condicion)
    print(f"  {'ok  ' if condicion else 'FALLA'} {nombre}{(' · ' + detalle) if detalle else ''}")


def main():
    print("tick congelado")
    try:
        r = subprocess.run([sys.executable, "-u", "-c", HIJO],
                           capture_output=True, text=True, timeout=45, cwd=RAIZ)
    except subprocess.TimeoutExpired:
        probar("el bucle no republica el estado congelado", False, "no terminó en 45 s")
        print("\nvivo_congelado: 1 fallos")
        return 1

    salida = (r.stdout or "").strip()
    linea = salida.splitlines()[-1] if salida else ""
    if not linea.startswith("{"):
        probar("el subproceso reporta medidas", False,
               (r.stderr or r.stdout or "")[-200:])
        print("\nvivo_congelado: 1 fallos")
        return 1

    d = json.loads(linea)
    probar("publica al principio", d["edad1"] is not None and d["edad1"] < 4.0,
           f"edad={None if d['edad1'] is None else round(d['edad1'], 1)}")
    # En el bug, acá la edad volvía a ~0 porque republicaba cada segundo.
    probar("a los 10 s la edad creció (no republica)",
           d["edad2"] is not None and d["edad2"] > 7.0,
           f"edad={None if d['edad2'] is None else round(d['edad2'], 1)} s")
    probar("con esa edad el panel diría congelado", d["edad2"] > d["umbral"],
           f"umbral={d['umbral']}")

    fallos = [k for k, v in HECHOS.items() if not v]
    print()
    if fallos:
        print(f"vivo_congelado: {len(fallos)} fallos -> {fallos}")
        return 1
    print(f"vivo_congelado: OK ({len(HECHOS)} comprobaciones)")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def test_suite():
    """Entrada para `pytest -q`.

    Las suites están escritas como scripts con `main()` que devuelve el número de
    fallos. Este envoltorio las expone a pytest sin cambiar su comportamiento
    (siguen corriendo también con `python3 tests/<archivo>.py`).
    """
    assert main() == 0

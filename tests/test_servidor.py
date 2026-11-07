"""El panel no debe fingir que hay datos frescos cuando dejó de llegar información.

Regresión del 2026-11-07: `/api/estado` devolvía el último payload para siempre, así que
si el stream se cortaba o la partida terminaba, el panel seguía diciendo "en vivo" con
una compra de hace minutos.
"""
import json
import os
import sys
import threading
import time
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import servidor as S  # noqa: E402

HECHOS = {}


def probar(nombre, condicion, detalle=""):
    HECHOS[nombre] = bool(condicion)
    print(f"  {'ok  ' if condicion else 'FALLA'} {nombre}{(' · ' + detalle) if detalle else ''}")


def consultar(puerto):
    with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/estado", timeout=5) as r:
        return json.loads(r.read().decode())


def main():
    print("frescura del estado servido")
    puerto = 8093
    S.EST.publicar({"listo": True, "t": 600, "almas": 1200, "fuente": "ocr"})
    hilo = threading.Thread(target=S.arrancar, args=(puerto,), daemon=True)
    hilo.start()
    time.sleep(1.5)

    reciente = consultar(puerto)
    probar("publica edad_s", reciente.get("edad_s") is not None, f"{reciente.get('edad_s')}")
    probar("recién publicado no es rancio", reciente.get("rancio") is False)

    # nadie publica durante más de 8 s: tiene que empezar a decirlo
    time.sleep(9)
    viejo = consultar(puerto)
    probar("tras 9 s sin datos, rancio=True", viejo.get("rancio") is True,
           f"edad={viejo.get('edad_s')} s")
    probar("la edad crece", (viejo.get("edad_s") or 0) >= 9, f"{viejo.get('edad_s')} s")
    probar("no se pierde el último estado", viejo.get("almas") == 1200)

    S.EST.publicar({"listo": True, "t": 601, "almas": 1300, "fuente": "ocr"})
    revivido = consultar(puerto)
    probar("al publicar de nuevo deja de ser rancio", revivido.get("rancio") is False)

    fallos = [k for k, v in HECHOS.items() if not v]
    print()
    if fallos:
        print(f"servidor: {len(fallos)} fallos -> {fallos}")
        return 1
    print(f"servidor: OK ({len(HECHOS)} comprobaciones)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

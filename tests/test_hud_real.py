"""Prueba contra recortes REALES del HUD, guardados en `verdad/hud_2026-11-09/`.

Por qué existe: hasta hoy el lector del HUD se probaba con imágenes sintéticas, y con
el juego abierto fallaba igual (el reloj salía vacío). Estos recortes vienen de una
ranked de verdad y están etiquetados a ojo, uno por uno, en `hud.json`.

Lo que se exige:
  - El reloj se lee EXACTO en los tres recortes.
  - El plan de apertura trae ítems reales del catálogo y con costo (aquí había un
    "800" en el sitio de un id: un costo haciendo de identificador).
  - El contador de almas: se informa lo que da el lector, sin exigir acierto todavía.
    El OCR de tesseract no puede con este font (0 de 12 configuraciones aciertan los
    cuatro recortes) y el banco de plantillas no tiene el glifo '6'. Cuando exista el
    banco del HUD, esta parte pasa a exigir 4 de 4.
"""
import json
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

CARPETA = os.path.join(RAIZ, "verdad", "hud_2026-11-09")


def _casos():
    with open(os.path.join(CARPETA, "hud.json"), encoding="utf-8") as f:
        return json.load(f)


def main():
    fallos = 0

    def check(nombre, condicion, detalle=""):
        nonlocal fallos
        if condicion:
            print(f"  ok   {nombre}")
        else:
            print(f"  FALLA {nombre} {detalle}")
            fallos += 1

    from PIL import Image

    from coach import hud
    from coach.fuentes import hud_rapido
    from coach.nucleo_demo import leer_conocimiento
    from coach.nucleo_vivo import plan_inicial

    datos = _casos()
    print(f"reloj ({len(datos['casos'])} recortes reales)")
    for caso in datos["casos"]:
        ruta = os.path.join(CARPETA, f"{caso['caso']}_reloj.png")
        recorte = Image.open(ruta).convert("RGB")
        texto = hud_rapido._ocr(recorte, (0, 0, recorte.width, recorte.height),
                                6, "0123456789:", "7")
        m = re.search(r"(\d{1,2}):(\d{2})", texto)
        leido = int(m.group(1)) * 60 + int(m.group(2)) if m else None
        check(f"{caso['caso']} = {caso['reloj']}", leido == caso["tiempo_s"],
              f"leyó {texto!r} ({leido})")

    print("id de partida")
    ruta = os.path.join(CARPETA, "match_id_full.png")
    leido = hud.leer_match_id(ruta)
    check("lee MATCH: 123456789 del recorte real", leido == 123456789, str(leido))

    print("plan de apertura")
    conoc = leer_conocimiento()
    plan = plan_inicial(conoc)
    items = conoc.get("items", conoc)
    check("trae cinco compras", len(plan) == 5, str(len(plan)))
    check("todos los id existen en el catálogo",
          all(p["id"] in items for p in plan),
          str([p["id"] for p in plan if p["id"] not in items]))
    check("todos con costo de 800",
          all(p.get("costo") == 800 for p in plan),
          str([(p["nombre"], p.get("costo")) for p in plan]))
    check("sin repetidos", len({p["id"] for p in plan}) == len(plan))

    print("contador de almas (informativo: todavía no se exige)")
    for caso in datos["casos"] + datos.get("suelto", []):
        ruta = os.path.join(CARPETA, f"{caso['caso']}_almas.png")
        if not os.path.exists(ruta):
            continue
        recorte = Image.open(ruta).convert("RGB")
        texto = hud_rapido._ocr(recorte, (20, 45, 200, 105), 4, "0123456789,", "7")
        print(f"  .... {caso['caso']}: esperado {caso['almas']}, leyó {texto!r}")

    print()
    if fallos:
        print(f"hud real: {fallos} fallos")
        return 1
    print("hud real: OK")
    return 0


def test_suite():
    """Entrada para `pytest -q`."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())

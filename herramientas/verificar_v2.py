#!/usr/bin/env python3
"""Comprueba que el Abrams Coach v2 está completo y en pie, sin abrir el juego.

    python3 herramientas/verificar_v2.py

Revisa las piezas que se fueron añadiendo y que fallan en silencio si desaparecen: la
captura por región, el estado del juego (menú/partida/cierre), el histórico de
composiciones, el camino por héroe, el panel web, el presupuesto del API y que nada
arranque solo. No sustituye a `pytest`: lo que hace es decir en una tabla qué está puesto
y qué falta, que es lo que se mira cuando algo se rompe a las dos partidas.

Sale con código 1 si algo falla.
"""
import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

FALLOS = []


def comprobar(nombre, funcion):
    try:
        ok, detalle = funcion()
    except Exception as exc:                                   # noqa: BLE001
        ok, detalle = False, f"{type(exc).__name__}: {exc}"
    marca = "ok  " if ok else "FALLA"
    print(f"  {marca} {nombre:<34} {detalle}")
    if not ok:
        FALLOS.append(nombre)
    return ok


def captura_por_region():
    from coach.fuentes import captura_kwin
    if not captura_kwin.disponible():
        return False, f"KWin ScreenShot2 no disponible ({captura_kwin._ESTADO.get('error')})"
    t0 = time.perf_counter()
    im = captura_kwin.capturar(360, 260, 720, 560)
    ms = (time.perf_counter() - t0) * 1000
    if im is None:
        return False, "la captura devolvió None"
    return ms < 50, f"{im.size[0]}x{im.size[1]} en {ms:.1f} ms"


def fase_del_juego():
    from coach.fuentes import log_juego
    if not log_juego.disponible():
        return True, "sin console.log (el juego no está instalado o no usó -condebug)"
    estado, frescura = log_juego.estado_ui()
    return True, (f"fase={log_juego.fase()} · mapa={log_juego.mapa()} · "
                  f"estado={estado} · log de hace {frescura:.0f} s")


def historico_composiciones():
    from coach import historico
    datos = historico.cargar()
    if not datos:
        return False, "falta data/historico.json.gz (herramientas/historico.py --construir)"
    pares = len(datos.get("pares") or {})
    return datos.get("total", 0) > 1000, f"{datos.get('total')} partidas · {pares} pares"


def items_por_heroe():
    from coach import items_comp
    tabla = items_comp.tabla_heroes()
    if not tabla:
        return False, "falta data/items_por_heroe.json (items_comp.guardar_por_heroe)"
    return len(tabla) >= 10, f"{len(tabla)} héroes con tabla"


def camino_por_heroe():
    from coach import camino_heroe
    partes = []
    for heroe in (6, 13):
        d = camino_heroe.cargar(heroe)
        partes.append(f"héroe {heroe}: {'sí' if d else 'no'}")
    hay = any(camino_heroe.cargar(h) for h in (6, 13))
    return hay, " · ".join(partes)


def apertura_por_heroe():
    from coach import apertura
    ids, fuente = apertura.resolver(None)
    return len(ids) >= 3, f"{len(ids)} ítems · {fuente}"


def archivo_local():
    import glob
    rutas = glob.glob(os.path.join(RAIZ, "data", "archivo", "*.jsonl.gz"))
    if not rutas:
        return False, "sin data/archivo (herramientas/archivo_abrams.py)"
    mb = sum(os.path.getsize(r) for r in rutas) / 1024 / 1024
    return True, f"{len(rutas)} archivos · {mb:.1f} MB"


def presupuesto_api():
    from coach.fuentes import api_analitica
    p = api_analitica.presupuesto()
    return True, (f"{p['usadas_ultima_hora']}/{p['tope_por_hora']} por hora · "
                  f"{p['de_cache']} de caché")


def panel_web():
    from coach.ui.web import PAGINA
    from coach import servidor
    limpio = all(x not in PAGINA for x in ("https://", "@import"))
    return ("/api/estado" in PAGINA and "/panel" in servidor.AVISO_RAIZ and limpio,
            f"{len(PAGINA)} bytes · sin dependencias externas")


def sin_autostart():
    import subprocess
    estado = subprocess.run(["systemctl", "--user", "is-enabled",
                             "abrams-coach-esperar.service"],
                            capture_output=True, text=True).stdout.strip()
    unidad = os.path.join(RAIZ, "arrancar.sh")
    return estado in ("disabled", "static", "not-found", ""), (
        f"servicio '{estado or 'no instalado'}' · lanzador {'presente' if os.path.exists(unidad) else 'falta'}")


def datos_de_decision():
    """Las cuatro piezas que el motor necesita para decidir, con su tamaño."""
    piezas = {"meta_abrams": "data/meta_abrams.json",
              "conocimiento": "data/conocimiento.json",
              "catálogo": "data/catalogo.json",
              "tipos de ítem": "data/items_tipos.json"}
    faltan = [n for n, r in piezas.items() if not os.path.exists(os.path.join(RAIZ, r))]
    return not faltan, f"{len(piezas) - len(faltan)}/{len(piezas)} piezas" + (
        f" · faltan {faltan}" if faltan else "")


def motor_v2():
    """Modo del valor por ítem: MEDIDO (artefacto válido) o CIEGO.

    CIEGO no es un fallo: desde el 2026-11-18 el artefacto se invalida a propósito cuando
    el corpus cambia (`coach/valor.py`), porque enseñar números de otro corpus es peor que
    no enseñarlos. Esta línea existe para que se sepa en qué modo está el motor sin abrir
    los docs.
    """
    try:
        sys.path.insert(0, RAIZ)
        from coach import valor
        modo = valor.modo()
        detalle = valor._cache.get("error") or ""
    except Exception as exc:                                  # noqa: BLE001
        return False, f"no se pudo cargar coach.valor: {exc}"
    if modo == "MEDIDO":
        return True, "MEDIDO · artefacto válido para el corpus"
    return True, ("CIEGO · sin evidencia por ítem (a propósito: "
                  + (detalle or "artefacto no disponible") + ")")


def main():
    print("Abrams Coach v2 · verificación de piezas\n")
    comprobar("captura por región (KWin)", captura_por_region)
    comprobar("fase del juego (menú/partida)", fase_del_juego)
    comprobar("histórico de composiciones", historico_composiciones)
    comprobar("ítems por héroe", items_por_heroe)
    comprobar("camino por héroe", camino_por_heroe)
    comprobar("apertura por héroe", apertura_por_heroe)
    comprobar("archivo local de partidas", archivo_local)
    comprobar("presupuesto del API", presupuesto_api)
    comprobar("panel web", panel_web)
    comprobar("nada arranca solo", sin_autostart)
    comprobar("datos del motor", datos_de_decision)
    comprobar("motor v2 (valor por ítem)", motor_v2)
    print()
    if FALLOS:
        print(f"{len(FALLOS)} pieza(s) con problemas: {', '.join(FALLOS)}")
        return 1
    print("todas las piezas en pie")
    return 0


if __name__ == "__main__":
    sys.exit(main())

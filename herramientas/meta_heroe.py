#!/usr/bin/env python3
"""Pozo temprano (apertura) de cualquier héroe, con la verdad de Abrams como control.

    python3 herramientas/meta_heroe.py --heroe abrams
    python3 herramientas/meta_heroe.py --heroe haze --guardar
    python3 herramientas/meta_heroe.py --heroe abrams --comparar

`--comparar` es el control de calidad: compara el pozo que sale del agregado público con
la apertura del banco de 626 partidas (`data/meta_abrams.json`). Si algún día deja de
acertar los tres, es que la regla de `coach/meta_heroe.py` dejó de valer y hay que
revisarla antes de usarla con otros héroes.

Las peticiones van por `coach/fuentes/api_analitica.py`: caché de 24 h en disco y tope de
120 peticiones por hora, así que repetir esto no cuesta cuota.
"""
import argparse
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import meta_heroe as M                                  # noqa: E402
from coach.fuentes import api_analitica as A                       # noqa: E402


def indice_heroes():
    ruta = os.path.join(RAIZ, "data", "heroes_index.json")
    with open(ruta, encoding="utf-8") as f:
        return {k.lower().replace(" ", "_"): int(v) for k, v in json.load(f).items()}


def resolver(nombre):
    nombre = str(nombre).strip().lower()
    if nombre.isdigit():
        return int(nombre)
    indice = indice_heroes()
    if nombre in indice:
        return indice[nombre]
    parecidos = [k for k in indice if nombre in k]
    if len(parecidos) == 1:
        return indice[parecidos[0]]
    raise SystemExit(f"héroe desconocido: {nombre}. Ejemplos: {', '.join(sorted(indice)[:8])}")


def todos(a):
    """Genera el pozo de cada héroe. El presupuesto de la API manda: si se agota, para."""
    ruta = os.path.join(RAIZ, "data", "heroes.json")
    with open(ruta, encoding="utf-8") as f:
        heroes = json.load(f)
    hechos, fallos = [], []
    for clave, info in sorted(heroes.items(), key=lambda kv: int(kv[0])):
        hero_id = int(clave)
        nombre = info.get("nombre", str(hero_id))
        try:
            d = M.desde_api(hero_id)
        except A.PresupuestoAgotado as exc:
            print(f"  {nombre:<14} saltado: {exc}")
            fallos.append(nombre)
            break
        except Exception as exc:                                   # noqa: BLE001
            print(f"  {nombre:<14} falla: {type(exc).__name__}: {exc}")
            fallos.append(nombre)
            continue
        pozo = ", ".join(c["nombre"] for c in d["apertura"][:3])
        print(f"  {nombre:<14} {pozo}")
        if a.guardar:
            M.guardar(hero_id, d, extra={"fuente": "api.deadlock-api.com item-stats",
                                         "generado": __import__("time").strftime(
                                             "%Y-%m-%dT%H:%M:%S")})
        hechos.append(nombre)
    print(f"\n{len(hechos)} héroes con pozo · {len(fallos)} sin datos · "
          f"presupuesto {A.presupuesto()['usadas_ultima_hora']}/"
          f"{A.presupuesto()['tope_por_hora']} por hora")
    return 0 if hechos else 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--heroe", help="nombre (abrams, haze...) o id")
    ap.add_argument("--todos", action="store_true",
                    help="todos los héroes de data/heroes.json (25 peticiones, con tope)")
    ap.add_argument("--guardar", action="store_true", help="escribir data/meta/<id>.json")
    ap.add_argument("--comparar", action="store_true",
                    help="comparar con la apertura del banco (solo Abrams tiene verdad)")
    ap.add_argument("--forzar", action="store_true", help="ignorar la caché de 24 h")
    a = ap.parse_args()

    if a.todos:
        return todos(a)
    if not a.heroe:
        ap.error("falta --heroe (o --todos)")
    hero_id = resolver(a.heroe)
    print(f"héroe {a.heroe} (id {hero_id}) · presupuesto {A.presupuesto()['usadas_ultima_hora']}"
          f"/{A.presupuesto()['tope_por_hora']} por hora")
    try:
        d = M.desde_api(hero_id, forzar=a.forzar)
    except A.PresupuestoAgotado as exc:
        print(f"sin presupuesto: {exc}. Se reutiliza lo que haya en disco.")
        guardado = M.cargar(hero_id)
        if not guardado:
            return 3
        d = guardado
    except Exception as exc:                                       # noqa: BLE001
        print(f"sin datos de la API ({type(exc).__name__}: {exc}). No se tocó nada.")
        return 2

    print(f"\npozo temprano · criterio ≤{d['criterio']['costo_max']} de oro, "
          f"comprado antes del {d['criterio']['rel_max']:.0f} % de la partida")
    print(f"  winrate base del héroe: {d['base_wr']:.1%} · muestra "
          f"{d['muestra']:,} partidas-ítem")
    for i, c in enumerate(d["apertura"], 1):
        print(f"  {i}. {c['nombre']:<22} {c['costo']:>5} oro · compra al "
              f"{c['rel_pct']:>4.1f} % · cota 95 % {c['wlb']:.1%} · n={c['muestra']:,}")

    if a.comparar or hero_id == 6:
        ruta = os.path.join(RAIZ, "data", "meta_abrams.json")
        try:
            with open(ruta, encoding="utf-8") as f:
                meta = json.load(f)
            esperados = [x["id"] for x in meta.get("apertura_detalle", [])][:3]
        except (OSError, ValueError, KeyError):
            esperados = []
        if esperados:
            r = M.comparar(d, esperados)
            estado = "OK" if r["faltan"] == [] else "REVISAR"
            print(f"\ncontrol contra el banco: {r['aciertos']}/{r['de']} "
                  f"de la apertura real · {estado}")
            if r["faltan"]:
                print(f"  faltan: {r['faltan']}")
            else:
                print("  el pozo contiene los tres ítems que compran los que ganan")

    if a.guardar:
        ruta = M.guardar(hero_id, d, extra={"fuente": "api.deadlock-api.com item-stats",
                                            "generado": __import__("time").strftime(
                                                "%Y-%m-%dT%H:%M:%S")})
        print(f"\nguardado: {os.path.relpath(ruta, RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

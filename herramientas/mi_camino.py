#!/usr/bin/env python3
"""Compara lo que el coach dijo con lo que Diego compró de verdad.

De dónde salen los datos: `salida/decisiones.jsonl` guarda, en cada lectura del coach,
el reloj de partida, las almas, el inventario completo y hasta tres recomendaciones.
Las compras no se registran como tales (la tabla `compras` está vacía), pero se
reconstruyen por diferencia de inventario entre dos lecturas seguidas. Eso da el
camino real sin tocar el juego ni pedirle nada al usuario.

Salidas:
  - apertura y camino habitual (la moda por posición, no un promedio)
  - coincidencia: cuántas compras fueron la 1.ª recomendación / estaban en el top-3
  - divergencias agrupadas, para ver el patrón y no la anécdota
  - `--fixture` escribe `salida/fixture-partidas.json`: los momentos de compra de cada
    partida, para usarlos como prueba de regresión antes de cambiar el motor.

Uso:
    python3 herramientas/mi_camino.py
    python3 herramientas/mi_camino.py --fixture
    python3 herramientas/mi_camino.py --min-juego 240   # segundos mínimos de sesión
"""
import argparse
import collections
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

LOG = os.path.join(RAIZ, "salida", "decisiones.jsonl")
ITEMS = os.path.join(RAIZ, "data", "items.json")
FIXTURE = os.path.join(RAIZ, "salida", "fixture-partidas.json")


def nombres():
    try:
        with open(ITEMS, encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return {}
    valores = datos.values() if isinstance(datos, dict) else datos
    return {str(v.get("id")): v.get("name") or str(v.get("id")) for v in valores}


def leer(ruta=LOG):
    if not os.path.exists(ruta):
        return []
    filas = []
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                filas.append(json.loads(linea))
            except ValueError:
                continue
    return filas


def sesiones(filas, hueco=300.0):
    """Corta el log en partidas cuando pasa más de `hueco` segundos sin escribir."""
    if not filas:
        return []
    salida, actual = [], [filas[0]]
    for antes, ahora in zip(filas, filas[1:]):
        if (ahora.get("ts") or 0) - (antes.get("ts") or 0) > hueco:
            salida.append(actual)
            actual = [ahora]
        else:
            actual.append(ahora)
    salida.append(actual)
    return salida


def jugables(todas, min_juego=240.0, min_lecturas=3):
    """Sesiones que son una partida de verdad y no el panel mirando el menú."""
    salida = []
    for s in todas:
        con_items = [r for r in s if r.get("items")]
        if len(con_items) < min_lecturas:
            continue
        if (s[-1].get("t") or 0) - (s[0].get("t") or 0) < min_juego:
            continue
        salida.append(s)
    return salida


def compras_de(sesion, nom):
    """[(t, id, nombre, recomendaciones_de_la_lectura_anterior)] por diferencia."""
    salida, previo, previas = [], None, []
    for r in sesion:
        actual = {str(i) for i in (r.get("items") or ())}
        if previo is not None and actual:
            for iid in actual - previo:
                salida.append((float(r.get("t") or 0), iid,
                               nom.get(iid, iid), list(previas)))
        if actual:
            previo = actual
            previas = list(r.get("recomendado") or ())
    return salida


def analizar(sesiones_jugables, nom):
    compras = [compras_de(s, nom) for s in sesiones_jugables]
    total = sum(len(c) for c in compras)
    en_primera = sum(1 for c in compras for _, _, n, recs in c
                     if recs and recs[0] == n)
    en_top3 = sum(1 for c in compras for _, _, n, recs in c if n in recs[:3])
    divergencias = collections.Counter()
    for c in compras:
        for _, _, n, recs in c:
            if not recs or n not in recs[:3]:
                divergencias[(recs[0] if recs else "—", n)] += 1
    return compras, total, en_primera, en_top3, divergencias


def camino_habitual(compras):
    """Moda por posición: lo que de verdad repite, no el promedio de todo."""
    columnas = collections.defaultdict(collections.Counter)
    for c in compras:
        for i, (_, _, nombre, _) in enumerate(c):
            columnas[i][nombre] += 1
    return {i: cont.most_common(1)[0] for i, cont in sorted(columnas.items())}


def _pasar_por_motor(config_json=None):
    """Re-juega cada compra del log con el motor de hoy y mide el acierto.

    Es la puerta de calidad de verdad: el test de `mi_camino` sin `--motor` mide lo que
    el coach dijo aquel día; con `--motor` mide lo que diría **ahora**, sobre el estado
    exacto que había (reloj, almas, inventario). Sin esto, cambiar el motor no se puede
    comparar con nada.
    """
    sys.path.insert(0, RAIZ)
    from coach.motor_api import Motor          # noqa: PLC0415

    cfg = json.loads(config_json) if config_json else None
    motor = Motor(cfg)
    nom = nombres()
    filas = jugables(sesiones(leer()))
    aciertos1 = aciertos3 = total = 0
    for s in filas:
        previo = None
        for r in s:
            actual = set(str(i) for i in (r.get("items") or ()))
            if previo is not None and actual and r.get("t") is not None:
                nuevos = actual - previo
                if nuevos:
                    estado = {"t": r.get("t"), "yo": {"heroe": "Abrams",
                              "almas": r.get("almas") or 0,
                              "items": sorted(previo)}}
                    rec = motor.analizar_dict(estado)
                    lista = [x.get("nombre") for x in (rec.get("recomendaciones") or [])]
                    for iid in nuevos:
                        nombre = nom.get(iid, iid)
                        total += 1
                        aciertos1 += 1 if lista[:1] == [nombre] else 0
                        aciertos3 += 1 if nombre in lista[:3] else 0
            if actual:
                previo = actual
    if not total:
        print("sin compras para re-jugar")
        return
    print(f"re-jugado con el motor: {total} compras · top-1 {aciertos1/total:.0%} "
          f"· top-3 {aciertos3/total:.0%}")


def main():
    ap = argparse.ArgumentParser(description="Tu camino real contra el del coach")
    ap.add_argument("--log", default=LOG)
    ap.add_argument("--min-juego", type=float, default=240.0)
    ap.add_argument("--fixture", action="store_true",
                    help="escribe salida/fixture-partidas.json para regresión")
    ap.add_argument("--silencio", action="store_true")
    ap.add_argument("--motor", action="store_true",
                    help="re-jugar el log con el motor actual y medir si acierta")
    ap.add_argument("--config", default=None,
                    help="json de configuración del motor para el modo --motor")
    args = ap.parse_args()

    nom = nombres()
    filas = leer(args.log)
    if not filas:
        print(f"sin log en {args.log}: abre el coach en una partida y vuelve")
        return 1
    s_jug = jugables(sesiones(filas), min_juego=args.min_juego)
    compras, total, primera, top3, div = analizar(s_jug, nom)

    dec = (lambda *a: None) if args.silencio else print
    dec(f"lecturas {len(filas)} · partidas completas {len(s_jug)} · compras {total}")
    if not total:
        print("no hay compras reconstruibles todavía (faltan partidas con inventario)")
        return 1
    dec(f"coincide con la 1.ª recomendación: {primera / total:.0%}")
    dec(f"estaba en el top-3:              {top3 / total:.0%}")

    dec("\nTU APERTURA (moda por posición)")
    for i, (nombre, veces) in camino_habitual(compras).items():
        if i >= 8:
            break
        dec(f"  {i + 1}. {nombre:28s} {veces}/{len(compras)} partidas")

    dec("\nDÓNDE TE FUISTE DEL COACH (coach decía → compraste tú)")
    for (dijo, hiso), veces in div.most_common(8):
        dec(f"  {dijo[:28]:30s} → {hiso[:28]:30s} x{veces}")

    if args.motor:
        _pasar_por_motor(args.config)
    if args.fixture:
        fixture = {"generado": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
                   "fuente": os.path.relpath(args.log, RAIZ),
                   "partidas": []}
        for s in s_jug:
            compras_s = compras_de(s, nom)
            fixture["partidas"].append({
                "inicio_t": s[0].get("t"),
                "fin_t": s[-1].get("t"),
                "heroe": next((r.get("heroe") for r in s if r.get("heroe")), None),
                "compras": [{"t": round(t), "item": n, "id": iid,
                             "coach": recs[:3]} for t, iid, n, recs in compras_s],
                "lecturas": len(s),
            })
        with open(FIXTURE, "w", encoding="utf-8") as f:
            json.dump(fixture, f, ensure_ascii=False, indent=1)
        dec(f"\nfixture: {os.path.relpath(FIXTURE, RAIZ)} "
            f"({len(fixture['partidas'])} partidas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Tesoros del meta: combinaciones que ganan más de lo que se usan.

La idea no es «qué compra la gente» sino «qué combinaciones ganan mucho con poca gente
usándolas». Eso es donde vive lo que el meta todavía no copió.

Fuente: `api.deadlock-api.com` → `/v1/analytics/item-permutation-stats`, que devuelve
victorias/derrotas por combinación de 2 o 3 ítems, filtrable por héroe, por muestra mínima
y por fecha. Con `--desde/--hasta` se puede medir un parche concreto y con `--comparar`
diffear contra una foto anterior: es el análisis histórico.

Qué hace, en orden:
  1. descarga las combinaciones del héroe en la ventana pedida;
  2. quita las que en realidad son un ítem y su componente (no son combo, son progresión);
  3. calcula winrate y su cota inferior de Wilson al 95% (para no premiar rachas de 3-0);
  4. compara contra el winrate base del héroe en esa misma ventana;
  5. marca las que llevan ítems que el camino del coach nunca recomienda.

Uso:
    python3 herramientas/tesoros.py                      # Abrams, pares, últimas 5 semanas
    python3 herramientas/tesoros.py --combo 3 --min-matches 200
    python3 herramientas/tesoros.py --desde 2026-08-01 --hasta 2026-09-01 --salida x.json
    python3 herramientas/tesoros.py --comparar data/tesoros/2026-09-01.json
"""
import argparse
import datetime as dt
import json
import math
import os
import sys
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

API = "https://api.deadlock-api.com"
H = {"User-Agent": "abrams-coach/1.0", "Accept": "application/json"}
HEROE = 6                      # Abrams
DESDE_DEFECTO = 1791676800     # 2026-10-11, el mínimo que acepta la API
GUARDADO = os.path.join(RAIZ, "data", "tesoros")


def _get(ruta, **params):
    url = API + ruta + ("?" + urllib.parse.urlencode(params) if params else "")
    for intento in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=H),
                                        timeout=120) as r:
                return json.load(r)
        except Exception:
            if intento == 2:
                raise
    return None


def unix(fecha):
    if fecha is None:
        return None
    return int(dt.datetime.strptime(fecha, "%Y-%m-%d")
               .replace(tzinfo=dt.timezone.utc).timestamp())


def wilson(victorias, n, z=1.96):
    """Cota inferior del winrate al 95%: castiga muestras chicas sin regalar nada."""
    if n <= 0:
        return 0.0
    p = victorias / n
    den = 1 + z * z / n
    centro = p + z * z / (2 * n)
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centro - margen) / den


def nombres():
    """id -> nombre, con el conocimiento del proyecto y el catálogo como respaldo."""
    salida = {}
    try:
        k = json.load(open(os.path.join(RAIZ, "data", "conocimiento.json"), encoding="utf-8"))
        for iid, d in k["items"].items():
            salida[str(iid)] = d.get("nombre") or str(iid)
    except Exception:                                        # noqa: BLE001
        pass
    try:
        items = json.load(open(os.path.join(RAIZ, "data", "items.json"), encoding="utf-8"))
        for iid, d in items.items():
            salida.setdefault(str(iid), d.get("name") or d.get("nombre") or str(iid))
    except Exception:                                        # noqa: BLE001
        pass
    return salida


def componentes():
    try:
        with open(os.path.join(RAIZ, "data", "componentes.json"), encoding="utf-8") as f:
            return {str(k): [str(x) for x in v] for k, v in json.load(f).items()}
    except Exception:                                        # noqa: BLE001
        return {}


def es_progresion(combo, mapa):
    """Un combo con un ítem y su componente no es una sinergia: es el mismo build."""
    ids = [str(x) for x in combo]
    for a in ids:
        for b in ids:
            if a != b and (a in mapa.get(b, []) or b in mapa.get(a, [])):
                return True
    return False


def camino_actual():
    """Ítems que el coach ya recomienda, para marcar lo que está «fuera del build»."""
    try:
        from coach.decision import camino as cm, heroe as heroes
        from coach.motor_api import Motor
        m = Motor()
        ruta = cm.construir(m.conoc, m.cat, heroes.cargar("abrams"))
        return {p["id"] for p in ruta}
    except Exception:                                        # noqa: BLE001
        return set()


def tiempos_y_costes(desde, hasta):
    """Tiempo medio de compra (API) y coste (catálogo local) por ítem.

    Sirve para estratificar: un combo de 12,800 no compite con uno de 1,600. Comparar
    winrates entre estratos distintos es lo que hacía ver «tesoros» que en realidad eran
    «los que iban ganando compraron caro».
    """
    tiempos = {}
    try:
        filas = _get("/v1/analytics/item-stats", hero_id=HEROE,
                     min_unix_timestamp=desde, max_unix_timestamp=hasta,
                     min_matches=100)
        for f in filas:
            tiempos[str(f["item_id"])] = float(f.get("avg_buy_time_s") or 0)
    except Exception:                                        # noqa: BLE001
        pass
    costes = {}
    try:
        items = json.load(open(os.path.join(RAIZ, "data", "items.json"), encoding="utf-8"))
        for iid, d in items.items():
            c = d.get("cost") or d.get("costo")
            if c:
                costes[str(iid)] = int(c)
    except Exception:                                        # noqa: BLE001
        pass
    return tiempos, costes


def estrato(ids, tiempos, costes):
    """(tramo de coste, tramo de minuto) para comparar peras con peras."""
    coste = sum(costes.get(i, 0) for i in ids) or 0
    t = [tiempos[i] for i in ids if i in tiempos]
    minuto = (sum(t) / len(t) / 60) if t else 0
    tramo_c = (0 if coste < 4000 else 1 if coste < 8000 else
               2 if coste < 12000 else 3 if coste < 16000 else 4)
    tramo_t = (0 if minuto < 12 else 1 if minuto < 20 else 2 if minuto < 30 else 3)
    return (tramo_c, tramo_t)


def base_heroe(desde, hasta, dur_min=None, dur_max=None, extra=None):
    """Winrate base de Abrams en la ventana (lo que hay que superar)."""
    extra = dict(extra or {})
    if dur_min:
        extra["min_duration_s"] = dur_min
    if dur_max:
        extra["max_duration_s"] = dur_max
    try:
        filas = _get("/v1/analytics/hero-stats", hero_id=HEROE,
                     min_unix_timestamp=desde, max_unix_timestamp=hasta, **extra)
        fila = filas[0]
        return fila["wins"] / max(1, fila["wins"] + fila["losses"])
    except Exception:                                        # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hero", type=int, default=HEROE)
    ap.add_argument("--combo", type=int, default=2)
    ap.add_argument("--min-matches", type=int, default=300)
    ap.add_argument("--dur-min", type=int, default=1800,
                    help="ventana de duración mínima (s). Controla el sesgo de partidas "
                         "largas: los ítems caros se compran cuando ya vas ganando")
    ap.add_argument("--dur-max", type=int, default=2400)
    ap.add_argument("--max-networth", type=int, default=None,
                    help="solo jugadores que terminaron con menos oro: mide remontadas, "
                         "no el efecto de ir ganando")
    ap.add_argument("--min-networth", type=int, default=None)
    ap.add_argument("--sin-ventana", action="store_true",
                    help="sin filtro de duración (para ver el sesgo crudo)")
    ap.add_argument("--max-matches", type=int, default=None)
    ap.add_argument("--desde", default=None, help="AAAA-MM-DD (default: hace 45 días)")
    ap.add_argument("--hasta", default=None, help="AAAA-MM-DD")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--salida", default=None)
    ap.add_argument("--comparar", default=None, help="snapshot anterior JSON para diffear")
    a = ap.parse_args()

    desde = unix(a.desde) or (int(dt.datetime.now(dt.timezone.utc).timestamp()) - 45 * 86400)
    hasta = unix(a.hasta)
    params = {"hero_id": a.hero, "comb_size": a.combo, "min_matches": a.min_matches,
              "min_unix_timestamp": desde}
    if hasta:
        params["max_unix_timestamp"] = hasta
    if a.max_matches:
        params["max_matches"] = a.max_matches
    if not a.sin_ventana:
        params["min_duration_s"] = a.dur_min
        params["max_duration_s"] = a.dur_max
    if a.max_networth:
        params["max_networth"] = a.max_networth
    if a.min_networth:
        params["min_networth"] = a.min_networth

    ventana = ("sin ventana de duración" if a.sin_ventana else
               f"partidas de {a.dur_min//60}-{a.dur_max//60} min")
    print(f"tesoros · Abrams · combos de {a.combo} · muestra mínima {a.min_matches} · "
          f"{ventana} · desde {dt.datetime.fromtimestamp(desde, dt.timezone.utc):%Y-%m-%d}")
    try:
        filas = _get("/v1/analytics/item-permutation-stats", **params) or []
    except Exception:                                        # noqa: BLE001
        print("sin datos de la API (¿red?). No se tocó nada.")
        return 2
    print(f"combinaciones descargadas: {len(filas)}")

    filtros_oro = {"min_networth": a.min_networth, "max_networth": a.max_networth}
    filtros_oro = {k: v for k, v in filtros_oro.items() if v}
    base = base_heroe(desde, hasta, None if a.sin_ventana else a.dur_min,
                      None if a.sin_ventana else a.dur_max, filtros_oro)
    base = base if base is not None else 0.5
    mapa = componentes()
    nom = nombres()
    ruta = camino_actual()

    tiempos, costes = tiempos_y_costes(desde, hasta)
    candidatos = []
    for f in filas:
        ids = [str(x) for x in f["item_ids"]]
        if es_progresion(ids, mapa):
            continue
        n = f["matches"]
        lcb = wilson(f["wins"], n)
        candidatos.append({
            "ids": ids,
            "nombres": [nom.get(i, i) for i in ids],
            "n": n,
            "winrate": round(f["wins"] / max(1, n), 4),
            "lcb": round(lcb, 4),
            "ventaja_pp": round((lcb - base) * 100, 2),
            "estrato": estrato(ids, tiempos, costes),
            "coste": sum(costes.get(i, 0) for i in ids),
            "fuera_del_build": [nom.get(i, i) for i in ids if i not in ruta],
        })

    # Dentro de cada estrato (coste y minuto de compra), comparar contra la mediana del
    # propio estrato. Sin esto, «Colossus + Magic Carpet» sale como tesoro solo porque
    # quien gana tiene oro para comprar dos 6,400.
    por_estrato = {}
    for c in candidatos:
        por_estrato.setdefault(c["estrato"], []).append(c["lcb"])
    for c in candidatos:
        mediana = sorted(por_estrato[c["estrato"]])[len(por_estrato[c["estrato"]]) // 2]
        c["ventaja_pp"] = round((c["lcb"] - mediana) * 100, 2)
        c["ventaja_vs_base_pp"] = round((c["lcb"] - base) * 100, 2)

    candidatos.sort(key=lambda x: -x["ventaja_pp"])
    # «Tesoro»: gana por encima del héroe y la muestra no es enorme (poca gente lo usa).
    tesoros = [c for c in candidatos if c["n"] <= (a.max_matches or 40_000)][:a.top]
    # «Trampa»: mucha gente lo compra y gana por debajo del héroe.
    trampas = sorted([c for c in candidatos if c["n"] >= 20_000],
                     key=lambda x: x["ventaja_pp"])[:a.top]

    print(f"\nwinrate base de Abrams en la ventana: {base:.1%}\n")
    print("TESOROS (por encima de la mediana de SU estrato coste/minuto):")
    for c in tesoros:
        fuera = " · fuera del build" if c["fuera_del_build"] else ""
        print(f"  {c['ventaja_pp']:+6.2f} pp  {c['winrate']:6.1%}  n={c['n']:>7,}  "
              f"{' + '.join(c['nombres'])}{fuera}")
    print("\nTRAMPAS (mucha gente y por debajo de su estrato):")
    for c in trampas:
        print(f"  {c['ventaja_pp']:+6.2f} pp  {c['winrate']:6.1%}  n={c['n']:>7,}  "
              f"{' + '.join(c['nombres'])}")

    if a.comparar and os.path.exists(a.comparar):
        try:
            prev = json.load(open(a.comparar, encoding="utf-8"))
        except Exception:                                    # noqa: BLE001
            prev = None
        if prev:
            antes = {tuple(sorted(c["ids"])): c for c in prev.get("tesoros", [])}
            ahora = {tuple(sorted(c["ids"])): c for c in tesoros}
            nuevos = [c for k, c in ahora.items() if k not in antes]
            print(f"\nnuevos desde {os.path.basename(a.comparar)}: {len(nuevos)}")
            for c in nuevos[:a.top]:
                print(f"  {c['ventaja_pp']:+6.2f} pp  {' + '.join(c['nombres'])}")

    datos = {
        "generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "heroe": a.hero,
        "combo": a.combo,
        "desde": dt.datetime.fromtimestamp(desde, dt.timezone.utc).strftime("%Y-%m-%d"),
        "hasta": (dt.datetime.fromtimestamp(hasta, dt.timezone.utc).strftime("%Y-%m-%d")
                  if hasta else None),
        "min_matches": a.min_matches,
        "dur_min": None if a.sin_ventana else a.dur_min,
        "dur_max": None if a.sin_ventana else a.dur_max,
        "max_networth": a.max_networth,
        "min_networth": a.min_networth,
        "base": round(base, 4),
        "tesoros": tesoros,
        "trampas": trampas,
        "total": len(candidatos),
    }
    ruta_salida = a.salida or os.path.join(
        GUARDADO, f"abrams-{datos['desde']}-{datos['hasta'] or 'hoy'}-c{a.combo}.json")
    os.makedirs(os.path.dirname(ruta_salida), exist_ok=True)
    with open(ruta_salida, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    print(f"\nJSON: {os.path.relpath(ruta_salida, RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

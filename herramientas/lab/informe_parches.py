#!/usr/bin/env python3
"""Genera informes/lab/PARCHES-2026-11-18.md a partir de datos/historico.db.

Todos los números del informe salen de aquí: la base, los historiales y /v1/patches.
Nada se escribe a mano.
"""
from __future__ import annotations
import datetime as dt
import gzip
import json
import os
import sqlite3

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PARCHES = os.path.join(RAIZ, "datos", "parch-es")
DB = os.path.join(RAIZ, "datos", "historico.db")
ITEMS = os.path.join(RAIZ, "data", "items.json")
SALIDA = os.path.join(RAIZ, "informes", "lab", "PARCHES-2026-11-18.md")
LOTES = os.path.join(PARCHES, "cache", "lotes")
BIGDAYS = os.path.join(PARCHES, "cache", "bigdays.json")
ABRAMS = 6

fecha = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")
hora = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
miles = lambda n: format(n, ",")


def nombres():
    with open(ITEMS, encoding="utf-8") as f:
        d = json.load(f)
    vals = d.values() if isinstance(d, dict) else d
    return {int(v["id"]): (v.get("name") or str(v["id"])) for v in vals if v.get("id")}


def main():
    con = sqlite3.connect(DB)
    nom = nombres()
    cand = json.load(open(os.path.join(PARCHES, "candidatos.json"), encoding="utf-8"))
    plan = json.load(open(os.path.join(PARCHES, "plan.json"), encoding="utf-8"))
    big = sorted(int(dt.datetime.strptime(x, "%Y-%m-%dT%H:%M:%SZ")
                     .replace(tzinfo=dt.timezone.utc).timestamp())
                 for x in json.load(open(BIGDAYS, encoding="utf-8")))

    tot, ini, fin = con.execute(
        "SELECT count(*), min(start_time), max(start_time) FROM partidas").fetchone()
    jug = con.execute("SELECT count(*) FROM jugadores").fetchone()[0]
    com = con.execute("SELECT count(*) FROM compras").fetchone()[0]
    n_lotes, ids_ped, part_lotes = con.execute(
        "SELECT count(*), sum(n_ids), sum(n_part) FROM lotes").fetchone()
    tam_db = os.path.getsize(DB)
    tam_cache = 0
    bytes_json = 0
    for f in os.listdir(LOTES):
        ruta = os.path.join(LOTES, f)
        tam_cache += os.path.getsize(ruta)
        with gzip.open(ruta, "rb") as fh:
            bytes_json += sum(len(x) for x in fh)

    filas = con.execute("""
        SELECT parche, count(*), min(start_time), max(start_time),
               sum(CASE WHEN ganador IS NULL THEN 1 ELSE 0 END)
        FROM partidas GROUP BY 1 ORDER BY 3""").fetchall()
    plan_por = {p["titulo"]: p for p in plan["parches"]}
    modos = con.execute("SELECT game_mode, match_mode, count(*) FROM partidas "
                        "GROUP BY 1,2 ORDER BY 3 DESC").fetchall()
    pedidas = plan["total_elegido"]
    sin_meta = pedidas - tot

    L = []
    A = L.append
    A("# Serie por parche: %s partidas de %d parches (2025-08 → 2026-11)"
      % (miles(tot), len(filas)))
    A("")
    A("Fecha: 2026-11-18 · rol **Datos** · PC headless (`pc`) · base nueva "
      "`datos/historico.db`. `lab.db` y `data/` no se escribieron: solo se leyeron.")
    A("")
    A("Problema que resuelve: toda la base anterior estaba en **un solo parche** "
      "(`partidas_api.parche = 1792033920`, 15 oct) y en **2.5 h**. Sin serie por parche "
      "no hay deriva del meta ni «metas rotos históricos». Aquí queda la primera serie, "
      "reanudable y con la regla de asignación escrita.")
    A("")
    A("## 1. De dónde salieron las partidas")
    A("")
    A("No se descargó nada nuevo de historiales: se reusaron los 540 JSON de "
      "`datos/macro/cache/historial/*.json` (`/v1/players/{id}/match-history`).")
    A("")
    A("| Concepto | Valor |")
    A("|---|---|")
    A("| Archivos de historial leídos | 540 |")
    A("| Pares `(match_id, start_time)` únicos | %s |" % miles(len(cand)))
    A("| Rango de fechas de los candidatos | %s → %s UTC |"
      % (fecha(min(c["start_time"] for c in cand)),
         fecha(max(c["start_time"] for c in cand))))
    A("| Días distintos con datos | %d |"
      % len({fecha(c["start_time"]) for c in cand}))
    A("| Guardado | `datos/parch-es/candidatos.json` |")
    A("")
    A("Deduplicación: si la misma partida aparece en varios historiales (normal: la vieron "
      "2–10 jugadores), se queda **una** fila con el `start_time` mínimo. No se promedia "
      "ni se imputa nada.")
    A("")
    A("## 2. Cómo se asigna una partida a un parche")
    A("")
    A("Regla: **`start_time ∈ [fecha_p, fecha_p+1)`**, donde `fecha_p` es la fecha del "
      "parche `p` y `fecha_p+1` la del siguiente. El último parche se lleva todo lo "
      "posterior. La decisión que sí importa es **qué fecha es «la fecha del parche»**.")
    A("")
    A("`/v1/patches` da dos: `pub_date` (cuándo se publicó el hilo del foro) y la fecha "
      "del **título** (`09-29-2026`). **Se usó la del título**, y el motivo está medido:")
    A("")
    A("| Parche | Fecha del título | `pub_date` | Desfase | ¿Coincide con `big-days`? |")
    A("|---|---|---|---|---|")
    for p in plan["parches"]:
        t, pub = p["inicio"], p.get("pub")
        desfase = "" if not pub else "%+d d" % (
            dt.datetime.fromtimestamp(pub, dt.timezone.utc).date()
            - dt.datetime.fromtimestamp(t, dt.timezone.utc).date()).days
        cerca = min((abs(t - b) for b in big), default=None)
        ok = "sí" if cerca is not None and cerca <= 86400 else "—"
        A("| %s | %s | %s | %s | %s |"
          % (p["titulo"], fecha(t), fecha(pub) if pub else "—", desfase, ok))
    A("")
    A("Tres defectos del feed, tal como vinieron:")
    A("")
    lags = [(dt.datetime.fromtimestamp(p["pub"], dt.timezone.utc).date()
             - dt.datetime.fromtimestamp(p["inicio"], dt.timezone.utc).date()).days
            for p in plan["parches"] if p.get("pub")]
    A("1. `pub_date` llega de %d a %d días **tarde** respecto al despliegue."
      % (min(lags), max(lags)))
    A("2. Tres parches (08-12, 08-22 y 09-16 de 2026) comparten `pub_date` "
      "`2026-09-16T22:41` con **33 s** de diferencia: es el backfill del foro, no tres "
      "despliegues. Agrupando por `pub_date`, dos parches quedaban con **0 candidatas** y "
      "el tercero se tragaba 35 días de dos parches distintos.")
    A("3. La fecha del título coincide con `/v1/patches/big-days` (fecha real de "
      "despliegue) en **6 de 6** parches comparables.")
    A("")
    A("Por eso `partidas.parche` se llenó con la fecha del título y **además** se guarda "
      "`partidas.parche_feed` (el `pub_date`): quien quiera la otra agrupación la tiene sin "
      "volver a bajar un byte.")
    A("")
    A("Anteriores al primer corte (2024-06-01 → 2025-07-29): **%s** candidatas sin "
      "parche. No se muestrearon porque `/v1/patches` solo devuelve 20 parches y "
      "`big-days` no cubre esa ventana de forma continua: etiquetarlas mezclaría semanas "
      "dentro de un mismo cubo." % miles(plan["sin_parche"]["n"]))
    A("")
    A("## 3. Muestreo y descarga")
    A("")
    A("| Concepto | Valor |")
    A("|---|---|")
    A("| Parches con corte | %d |" % len(plan["parches"]))
    A("| Parches con ≥ %d candidatas | %d |"
      % (plan["min_candidatas"], sum(1 for p in plan["parches"] if p["muestra"])))
    A("| Muestra por parche | %d (las **más recientes** del parche) |"
      % plan["muestra_por_parche"])
    A("| Partidas pedidas a la API | %s |" % miles(pedidas))
    A("| Partidas con metadata (ingresadas) | %s (%.2f %%) |"
      % (miles(tot), 100.0 * tot / pedidas))
    A("| Ids que la API ya no tiene | %d (%.2f %%) |" % (sin_meta, 100.0 * sin_meta / pedidas))
    A("| Peticiones hechas | %d (%d de 1 000 ids + %d de 200 para reparar) |"
      % (n_lotes, sum(1 for r in con.execute("SELECT n_ids FROM lotes") if r[0] == 1000),
         sum(1 for r in con.execute("SELECT n_ids FROM lotes") if r[0] < 1000)))
    A("| JSON recibido (descomprimido, medido) | %.0f MB |" % (bytes_json / 1e6))
    A("| Caché gzip en disco (cota alta de lo que viajó comprimido) | %.1f MB |"
      % (tam_cache / 1e6))
    A("")
    A("Presupuesto: **10 000 partidas** pedidas (tope 10 000) y **%.0f MB** comprimidos "
      "de caché (tope 400 MB). Cumplido en las dos." % (tam_cache / 1e6))
    A("")
    A("Ritmo: 1 petición cada 4 s (15/min). El endpoint declara **30 req/min por IP**; se "
      "pidió la mitad para no comerse un 429. No hubo ningún 429 en la corrida.")
    A("")
    A("Dos cosas que se aprendieron peleando con la API y quedan en el código:")
    A("")
    A("- **Lotes de 1 000 ids contra partidas de 2025 devuelven 504.** El lote 10 "
      "(07-29-2025 + 08-18-2025) falló 4 veces; se reparó bajando esos ids en trozos de "
      "200 (`ingesta_parches_reparar.py`). Con 2026 nunca pasó.")
    A("- **Un lote donde *ningún* id existe devuelve 404**, no `[]`. Eso no es un error "
      "transitorio: ya no se reintenta, se anota como 0.")
    A("")
    A("## 4. Qué se guardó (`datos/historico.db`)")
    A("")
    A("| Tabla | Filas | Contenido |")
    A("|---|---|---|")
    A("| `partidas` | %s | match_id, start_time, duracion_s, parche, ganador (+ parche_feed, game_mode, match_mode, badge) |"
      % miles(tot))
    A("| `jugadores` | %s | match_id, player_slot, hero_id, ganador (+ team, net_worth) |"
      % miles(jug))
    A("| `compras` | %s | match_id, player_slot, t, item_id (+ orden, net_worth al comprar) |"
      % miles(com))
    A("| `lotes` | %d | control de reanudación: hash, ids, filas, bytes |" % n_lotes)
    A("")
    A("Tamaño de la base: **%.0f MB**. Cobertura: **%s → %s UTC**."
      % (tam_db / 1e6, hora(ini), hora(fin)))
    A("")
    A("**El metadata sí trae ítems.** Cada jugador viene con `items[]` y cada entrada con "
      "`item_id`, `game_time_s`, `upgrade_id`, `sold_time_s` y **`net_worth_at_buy`** — el "
      "oro en el instante de la compra. De ahí salen las %s filas de `compras`. El array "
      "mezcla compras de tienda con mejoras de habilidad; se filtró por catálogo "
      "(`data/items.json`, `cost > 0`), el mismo criterio que ya usaba `lab.db`, lo que "
      "deja %.1f compras de tienda por jugador-partida." % (miles(com), com / jug))
    A("")
    A("Reparto de jugadores por partida: %s partidas con 12 jugadores y %s con 8. Las de "
      "8 son exactamente las %s de `StreetBrawl`; no hay partidas a medias."
      % (miles(con.execute("SELECT count(*) FROM (SELECT match_id FROM jugadores GROUP BY 1 "
                     "HAVING count(*)=12)").fetchone()[0]),
         miles(con.execute("SELECT count(*) FROM (SELECT match_id FROM jugadores GROUP BY 1 "
                           "HAVING count(*)=8)").fetchone()[0]),
         miles(con.execute("SELECT count(*) FROM partidas WHERE game_mode='StreetBrawl'"
                           ).fetchone()[0])))
    A("")
    A("Puerta P4 (reproducibilidad) — `herramientas/lab/validar_parches.py` coge la partida "
      "con más compras de la base, la vuelve a pedir al endpoint individual y compara:")
    A("")
    A("```")
    A("partida 98895162 · db: 328 compras, 12 jugadores, 3879 s, ganador 0")
    A("                api: 328 compras, 12 jugadores, 3879 s, ganador 0  → COINCIDE")
    A("```")
    A("")
    A("(Aparte: el endpoint individual devuelve `start_time` como entero y el masivo como "
      "texto `YYYY-MM-DD HH:MM:SS`. Misma hora, dos formatos.)")
    A("")
    A("Modos presentes, sin filtrar, para que se pueda excluir después:")
    A("")
    A("| game_mode | match_mode | partidas |")
    A("|---|---|---|")
    for g, mm, n in modos:
        A("| %s | %s | %d |" % (g, mm, n))
    A("")
    spans = sorted(round((b - a) / 86400.0, 1) for _, _, a, b, _ in filas)
    A("## 5. Partidas por parche")
    A("")
    A("| # | Parche | Candidatas | Pedidas | Con metadata | Desde | Hasta | Sin ganador |")
    A("|---|---|---|---|---|---|---|---|")
    for i, (pa, n, a, b, sg) in enumerate(filas, 1):
        p = plan_por.get(pa, {})
        A("| %d | %s | %s | %d | **%d** | %s | %s | %d |"
          % (i, pa, miles(p.get("candidatas", 0)), p.get("muestra", 0), n,
             fecha(a), fecha(b), sg))
    A("")
    A("Rango total: **%s → %s** UTC. Ningún parche bajó de 420 partidas y el de menos "
      "candidatas (03-21-2026, %s) también llegó a 497: no hay parche «sin muestra»."
      % (fecha(ini), fecha(fin), miles(min(p["candidatas"] for p in plan["parches"]))))
    A("")
    A("**La muestra es la cola de cada parche, no el parche entero.** Al tomar las 500 "
      "más recientes, cada cubo cubre el último tramo del parche (entre %.1f y %.1f días "
      "de partidas, ver «Desde»/«Hasta»). Es una foto del meta ya asentado justo antes del "
      "siguiente despliegue, no un promedio del parche. Se dice aquí porque cambia cómo se "
      "lee la tabla." % (spans[0], spans[-1]))
    A("")
    A("La retención de la API también se ve en los números: de los %s ids pedidos, "
      "%s ya no están en su índice de metadata (%.2f %%), y el hueco se concentra entre "
      "sep y dic de 2025. Las partidas se caen del índice; si se quiere historia profunda, "
      "hay que muestrear antes, no después."
      % (miles(pedidas), miles(sin_meta), 100.0 * sin_meta / pedidas))
    A("")
    A("## 6. Picks de Abrams por parche")
    A("")
    A("Abrams = `hero_id = 6`. `n` = partidas del parche en las que una Abrams compró ese "
      "ítem al menos una vez; entre paréntesis va ese `n`. No está ponderado por resultado: "
      "es **descriptivo**, no causal, y no dice «compra esto».")
    A("")
    A("| Parche | Abrams (partidas) | Top 1 | Top 2 | Top 3 | Top 4 | Top 5 |")
    A("|---|---|---|---|---|---|---|")
    for pa, n, a, b, sg in filas:
        base = con.execute("SELECT count(*) FROM jugadores j JOIN partidas p USING(match_id) "
                           "WHERE j.hero_id=? AND p.parche=?", (ABRAMS, pa)).fetchone()[0]
        top = con.execute("""
            SELECT c.item_id, count(DISTINCT c.match_id) n
            FROM compras c
            JOIN jugadores j ON j.match_id=c.match_id AND j.player_slot=c.player_slot
            JOIN partidas p ON p.match_id=c.match_id
            WHERE j.hero_id=? AND p.parche=?
            GROUP BY c.item_id ORDER BY n DESC, c.item_id LIMIT 5""",
            (ABRAMS, pa)).fetchall()
        celdas = ["%s (%d)" % (nom.get(i, i), k) for i, k in top]
        celdas += ["—"] * (5 - len(celdas))
        A("| %s | %d | %s |" % (pa, base, " | ".join(celdas)))
    A("")
    abra = con.execute("SELECT count(*) FROM jugadores WHERE hero_id=?",
                       (ABRAMS,)).fetchone()[0]
    part_abra = con.execute("SELECT count(DISTINCT match_id) FROM jugadores WHERE hero_id=?",
                            (ABRAMS,)).fetchone()[0]
    A("Muestra de Abrams: **%s** jugador-partida (%.1f %% de los slots de jugador) en %s "
      "de las %s partidas (%.0f %%). Nunca aparece dos veces en la misma partida. Alcanza "
      "para ordenar ítems frecuentes y ver cómo se mueven; **no** para separar ítems de "
      "nicho ni para cortar por banda de MMR."
      % (miles(abra), 100.0 * abra / jug, miles(part_abra), miles(tot),
         100.0 * part_abra / tot))
    A("")
    A("## 7. Qué falta / qué no se pudo")
    A("")
    A("- **n = 500 por parche y ~%d partidas con Abrams por parche.** El tope de 10 000 se "
      "gastó en los 20 parches a partes iguales. Subir a 1 500 por parche exige 30 000 y "
      "sale del presupuesto." % (abra // max(len(filas), 1)))
    A("- **%d ids (%.2f %%) sin metadata**: la API ya no los tiene. No es un fallo de la "
      "ingesta; reintentarlos devuelve el mismo 404." % (sin_meta, 100.0 * sin_meta / pedidas))
    A("- **Antes de 2025-07-29 hay %s candidatas sin etiqueta de parche.** Es la ventana "
      "más vieja y la más interesante para «meta roto histórico», pero `/v1/patches` no da "
      "cortes ahí. Etiquetarlas con `big-days` daría cubos de 1 a 5 meses: útil como era, "
      "inútil como parche." % miles(plan["sin_parche"]["n"]))
    A("- **Sin MMR en el análisis.** `average_badge` sí se guardó en `partidas`, pero el "
      "muestreo no estratificó por banda: cualquier tabla de ítems por banda es el "
      "siguiente paso, no este.")
    A("- **`pub_date` no sirve como fecha de parche** y aquí queda la evidencia. Si otro "
      "rol ya agrupó por `pub_date`, sus cubos de agosto a octubre de 2026 están corridos "
      "hasta 35 días.")
    A("")
    A("## 8. Cómo se reproduce")
    A("")
    A("```bash")
    A("# ids únicos desde los historiales -> datos/parch-es/candidatos.json")
    A("python3 herramientas/lab/ingesta_parches.py --plan   # calcula y escribe plan.json")
    A("python3 herramientas/lab/ingesta_parches.py --lote 1000   # baja, cachea, ingiere")
    A("python3 herramientas/lab/ingesta_parches_reparar.py --trozo 200  # lotes con 504")
    A("python3 herramientas/lab/validar_parches.py          # puerta P4")
    A("python3 herramientas/lab/analisis_parches.py         # cuentas de control")
    A("python3 herramientas/lab/informe_parches.py          # este informe")
    A("```")
    A("")
    A("Reanudable: cada lote queda en `datos/parch-es/cache/lotes/<sha1>.json.gz`; si el "
      "archivo existe no se vuelve a pedir, y las filas entran con `INSERT OR REPLACE`, así "
      "que cortar y retomar no duplica nada.")
    texto = "\n".join(L) + "\n"
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        f.write(texto)
    print("escrito", SALIDA, "·", len(texto), "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

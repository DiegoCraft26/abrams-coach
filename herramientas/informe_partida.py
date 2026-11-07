#!/usr/bin/env python3
"""Informe de una partida ya archivada: números primero, una lectura del modelo después.

Reemplaza al chat: nadie escribe a media partida. Al terminar, la app ya tiene las
muestras y las recomendaciones en SQLite; este comando las convierte en una página con lo
que pasó y, si se pide, una interpretación corta del modelo (una sola llamada, con el
resumen de datos delante para que no invente).

Uso:
    python3 herramientas/informe_partida.py --match 132869067
    python3 herramientas/informe_partida.py --ultimas 3 --sin-modelo
"""
import argparse
import datetime
import json
import os
import statistics
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

DB = os.path.join(RAIZ, "datos", "coach.db")


def _conectar(ruta):
    import sqlite3
    if not os.path.exists(ruta):
        return None
    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    return con


def digest(con, match_id):
    """Todo lo que se puede decir sin modelo, en un dict."""
    filas = con.execute("select * from muestras where match_id=? order by ts",
                        (match_id,)).fetchall()
    recos = con.execute("select * from recomendaciones where match_id=? order by ts",
                        (match_id,)).fetchall()
    partida = con.execute("select * from partidas where match_id=?", (match_id,)).fetchone()
    video = con.execute("select ruta from videos where match_id=?", (match_id,)).fetchone()

    almas = [f["almas"] for f in filas if f["almas"] is not None]
    tiempos = [f["t"] for f in filas if f["t"] is not None]
    estados = {}
    for f in filas:
        if f["estado"]:
            estados[f["estado"]] = estados.get(f["estado"], 0) + 1
    items = {}
    for r in recos:
        if r["item"]:
            items[r["item"]] = items.get(r["item"], 0) + 1

    # Métricas derivadas: sin esto el informe repite cifras y no dice nada.
    oro = [f["oro"] for f in filas if f["oro"] is not None]
    minutos = ((max(tiempos) - min(tiempos)) / 60.0) if tiempos and len(tiempos) > 1 else 0
    almas_por_min = None
    if minutos > 1 and almas and len(almas) > 1:
        almas_por_min = round((almas[-1] - almas[0]) / minutos)
    # "Tuvo el oro para la recomendación y no la compró": eso sí es una compra tardía.
    # Antes se contaba "oro >= 1,600", que no prueba nada (podías estar ahorrando para
    # un ítem de 3,200) y el hallazgo salía falso.
    costos = {}
    for r in recos:
        if r["ts"] is not None and r["costo"]:
            costos.setdefault(round(r["ts"], 1), []).append(r["costo"])
    pagables = evaluables = 0
    for f in filas:
        if f["oro"] is None or f["ts"] is None:
            continue
        lista = costos.get(round(f["ts"], 1))
        if not lista:
            continue
        evaluables += 1
        if f["oro"] >= min(lista):
            pagables += 1
    oro_parado = (pagables / evaluables) if evaluables else None
    top1 = None
    if items:
        nombre, veces = max(items.items(), key=lambda x: x[1])
        top1 = {"nombre": nombre, "veces": veces,
                "pct": round(100 * veces / max(1, len(recos)))}
    return {
        "match_id": match_id,
        "muestras": len(filas),
        "recomendaciones": len(recos),
        "ventana_s": [min(tiempos), max(tiempos)] if tiempos else None,
        "almas": {"min": min(almas) if almas else None,
                  "max": max(almas) if almas else None,
                  "mediana": int(statistics.median(almas)) if almas else None},
        "estados": estados,
        "top_recomendaciones": sorted(items.items(), key=lambda x: -x[1])[:8],
        "almas_por_min": almas_por_min,
        "pct_podia_comprar": round(100 * oro_parado) if oro_parado is not None else None,
        "muestras_con_oro_evaluables": evaluables,
        "top1": top1,
        "minutos": round(minutos, 1),
        "duracion_s": partida["duracion_s"] if partida else None,
        "resultado": partida["resultado"] if partida else None,
        "video": video["ruta"] if video else None,
    }


def hallazgos(d):
    """Lo que dicen los números, escrito aquí y no por el modelo.

    Cada hallazgo se sostiene con un dato del digest; si el dato falta, no se escribe.
    """
    salida = []
    estados = d.get("estados") or {}
    total = sum(estados.values()) or 0
    if total:
        farm = estados.get("FARM", 0) * 100 // total
        if farm >= 40:
            salida.append(f"{farm}% de las muestras estuvieron en FARM: la partida se fue "
                          f"en recuperar almas, no en pelear.")
        pelear = estados.get("PELEAR", 0) * 100 // total
        if pelear >= 40:
            salida.append(f"{pelear}% de las muestras en PELEAR: se jugó con ventaja y se "
                          f"aprovechó.")
    pct_oro = d.get("pct_podia_comprar")
    if pct_oro is not None and pct_oro >= 30:
        salida.append(f"En {pct_oro}% de las muestras el oro alcanzaba para lo que el motor "
                      f"recomendaba y no se compró: compra tardía.")
    top1 = d.get("top1")
    if top1 and top1["pct"] >= 50:
        salida.append(f"El motor repitió «{top1['nombre']}» en {top1['pct']}% de las "
                      f"recomendaciones: poca variedad para {d['minutos']} minutos.")
    apm = d.get("almas_por_min")
    if apm is not None and apm > 0:
        salida.append(f"Ritmo de {apm:,} almas por minuto observadas.")
    if d.get("resultado") is None:
        salida.append("La partida no tiene resultado guardado: no se puede cruzar con "
                      "victoria o derrota.")
    return salida


def redactar(d, proveedor=None):
    """Una sola llamada al modelo con el digest delante. Devuelve texto o None."""
    if proveedor is None:
        try:
            from coach.agente.proveedor import ProveedorConRespaldo, cadena_por_defecto
            proveedor = ProveedorConRespaldo(cadena_por_defecto())
        except Exception:                                    # noqa: BLE001
            return None
    sistema = (
        "Reescribes una lista de hallazgos sobre una partida de Deadlock en un párrafo "
        "breve para el jugador. Español de México, seco, sin adornos y sin emojis. "
        "Reglas duras: no añadas cifras que no estén en los hallazgos; no propongas nada "
        "que no se deduzca de ellos; máximo 4 líneas. Si la lista está vacía, escribe "
        "«no hay nada que destacar en esta partida».")
    usuario = json.dumps(d, ensure_ascii=False)
    r = proveedor.chat([{"role": "system", "content": sistema},
                        {"role": "user", "content": usuario}])
    if not isinstance(r, dict) or r.get("error"):
        return None
    try:
        return r["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        return None


def escribir(d, texto, salida):
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    lineas = [f"# Partida {d['match_id']}", ""]
    lineas.append(f"- Muestras: {d['muestras']} · recomendaciones: {d['recomendaciones']}")
    if d["ventana_s"]:
        a, b = d["ventana_s"]
        lineas.append(f"- Ventana observada: {int(a)//60}:{int(a)%60:02d} a "
                      f"{int(b)//60}:{int(b)%60:02d}")
    if d["almas"]["mediana"] is not None:
        lineas.append(f"- Almas: {d['almas']['min']:,} → {d['almas']['max']:,} "
                      f"(mediana {d['almas']['mediana']:,})")
    if d["estados"]:
        total = sum(d["estados"].values()) or 1
        reparto = ", ".join(f"{k} {v*100//total}%"
                            for k, v in sorted(d["estados"].items(), key=lambda x: -x[1]))
        lineas.append(f"- Estados: {reparto}")
    if d["top_recomendaciones"]:
        lineas.append("- Recomendado: " + ", ".join(
            f"{n} ({c})" for n, c in d["top_recomendaciones"]))
    if d["duracion_s"]:
        lineas.append(f"- Duración: {d['duracion_s']//60} min · resultado "
                      f"{d['resultado'] or 'desconocido'}")
    if d["video"]:
        lineas.append(f"- Video: `{d['video']}`")
    lineas += ["", "## Hallazgos", ""]
    lineas += [f"- {h}" for h in (d.get("hallazgos") or ["nada que destacar"])]
    lineas += ["", "## Lectura", "",
               texto or "(sin modelo: los hallazgos de arriba son todo lo que hay)", ""]
    with open(salida, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))
    return salida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", type=int, default=None)
    ap.add_argument("--ultimas", type=int, default=1)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--salida", default=os.path.join(RAIZ, "informes", "partidas"))
    ap.add_argument("--sin-modelo", action="store_true")
    a = ap.parse_args()

    con = _conectar(a.db)
    if con is None:
        print(f"no existe la base {a.db}: corre herramientas/archivar.py primero")
        return 1

    if a.match:
        ids = [a.match]
    else:
        ids = [r["match_id"] for r in con.execute(
            "select match_id, count(*) n from muestras group by match_id "
            "order by max(ts) desc limit ?", (a.ultimas,))]
    if not ids:
        print("la base no tiene muestras: nada que informar")
        return 1

    proveedor = None
    if not a.sin_modelo:
        try:
            from coach.agente.proveedor import ProveedorConRespaldo, cadena_por_defecto
            proveedor = ProveedorConRespaldo(cadena_por_defecto())
        except Exception as exc:                             # noqa: BLE001
            print(f"sin modelo ({type(exc).__name__}): el informe sale solo con números")

    for mid in ids:
        d = digest(con, mid)
        d["hallazgos"] = hallazgos(d)
        texto = redactar(d, proveedor)
        salida = os.path.join(a.salida, f"{mid}.md")
        escribir(d, texto, salida)
        print(f"{mid}: {d['muestras']} muestras, {d['recomendaciones']} recomendaciones "
              f"-> {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

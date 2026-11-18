"""El camino de compra de un héroe, derivado de partidas reales.

El coach solo tenía el camino de Abrams, y venía de dos fuentes distintas: el cache local
de 626 partidas (para los tramos de compra) y una lista escrita a mano (para la apertura).
Para otros héroes no había nada.

Esto deriva lo mismo que `data/meta_abrams.json` desde cualquier conjunto de timelines:

    abrir   qué se compra antes del minuto 10, entre los que ganan
    tramos  0-10, 10-20, 20-30 y 30+ con la muestra de cada ítem
    primera qué se compra primero y cuántas veces

Cuidado medido: contar compras de todos (ganen o pierdan) describe el meta, no lo que
funciona. Se puede pedir `solo_ganadoras=True`, que es lo que usa la apertura. Y siempre
se devuelve `n` para que nadie lea un camino de 20 partidas como si fuera de 20 000.
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOGO = os.path.join(RAIZ, "data", "catalogo.json")
MIN_N = 50


def _catalogo(ruta=None):
    try:
        with open(ruta or CATALOGO, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def tramo(t):
    if t < 600:
        return "0-10"
    if t < 1200:
        return "10-20"
    if t < 1800:
        return "20-30"
    return "30+"


def _compras(partida, solo_tienda=True):
    """[(id, segundo)] de la partida, sin repetir el mismo ítem dos veces.

    `solo_tienda` descarta las subidas de habilidad que el metadata mete en el mismo
    array: sin este filtro la «apertura» de Abrams salía Shoulder Charge, Infernal
    Resilience y Seismic Impact, que son sus habilidades (medido 2026-11-15).
    """
    from .fuentes import items_assets
    tipos = items_assets.cargar() if solo_tienda else {}
    vistos = {}
    for fila in partida.get("items") or []:
        try:
            iid, t = int(fila[0]), int(fila[1])
        except (IndexError, TypeError, ValueError):
            continue
        if solo_tienda and not items_assets.es_item(iid, tipos):
            continue
        if iid not in vistos or t < vistos[iid]:
            vistos[iid] = t
    return sorted(vistos.items(), key=lambda x: x[1])


def derivar(partidas, catalogo=None, solo_ganadoras=False, top=10, min_n=MIN_N):
    """Estructura de camino: {'n_partidas', 'apertura', 'tramos', 'primera_compra'}."""
    catalogo = catalogo if catalogo is not None else _catalogo()
    total = 0
    tramos = defaultdict(Counter)
    primera = Counter()
    for p in partidas:
        if p.get("items") is None:
            continue
        gano = p.get("gano", p.get("gane"))
        if solo_ganadoras and not gano:
            continue
        total += 1
        compras = _compras(p)
        if compras:
            primera[compras[0][0]] += 1
        for iid, t in compras:
            tramos[tramo(t)][iid] += 1
    if not total:
        return {"n_partidas": 0, "apertura": [], "tramos": {}, "primera_compra": []}

    def fila(iid, n):
        info = catalogo.get(str(iid)) or {}
        return {"id": str(iid), "nombre": info.get("nombre") or str(iid),
                "costo": info.get("costo"), "n": n}

    salida = {"n_partidas": total, "solo_ganadoras": bool(solo_ganadoras),
              "tramos": {}, "apertura": [], "primera_compra": []}
    for nombre in ("0-10", "10-20", "20-30", "30+"):
        cubo = tramos.get(nombre) or Counter()
        salida["tramos"][nombre] = [fila(iid, n) for iid, n in cubo.most_common(top)
                                    if n >= min_n]
    # La apertura son los ítems del primer tramo que además se compran primero, en orden
    # de frecuencia: si algo no es de apertura, no aparece entre los más comprados ahí.
    apertura = [f for f in salida["tramos"]["0-10"] if f["n"] >= max(min_n, 20)][:5]
    salida["apertura"] = apertura
    salida["primera_compra"] = [fila(iid, n) for iid, n in primera.most_common(5)
                                if n >= min_n]
    return salida


def desde_archivo(heroe, carpeta=None, solo_ganadoras=True):
    """Deriva el camino leyendo el archivo local de ese héroe (timelines con compras)."""
    from . import items_comp

    partidas = items_comp.cargar(carpeta=carpeta, heroe=heroe)
    return derivar(partidas, solo_ganadoras=solo_ganadoras)


def plan_para(hero_id, t_s, cuantos=5, camino=None):
    """Los ítems del tramo en el que va la partida, en el formato del panel.

    Es lo que el coach puede ofrecer a un héroe que no es Abrams: el motor de economía
    solo tiene la ruta de Abrams, pero el camino observado de ese héroe sí existe y sirve
    para decir «en tu minuto 14 se compra esto», con su muestra y sin puntuación inventada.
    Devuelve None si no hay camino guardado para ese héroe.
    """
    datos = camino if camino is not None else cargar(hero_id)
    if not datos:
        return None
    tramos = datos.get("tramos") or {}
    clave = tramo(max(0, int(t_s or 0)))
    filas = tramos.get(clave) or tramos.get("0-10") or []
    salida = []
    for f in filas[:cuantos]:
        salida.append({"id": str(f.get("id")), "nombre": f.get("nombre"),
                       "costo": f.get("costo"), "n": f.get("n"),
                       "icono": f"/icono/{f.get('id')}"})
    return salida or None


def aplicar_a_salida(salida, heroe_jugado):
    """Si el héroe no es Abrams, cambia el plan por su camino observado.

    Devuelve True si aplicó algo. Se saca del bucle para poder probarlo: en el bucle
    quedaba enterrado y solo se podía comprobar abriendo el panel en una partida.
    """
    if not isinstance(salida, dict) or not heroe_jugado:
        return False
    nombre = str(heroe_jugado).strip().lower()
    if nombre in ("abrams", "6", ""):
        return False
    from . import historico
    hero_id = int(nombre) if nombre.isdigit() else historico.nombre_a_id().get(nombre)
    if not hero_id:
        return False
    plan = plan_para(hero_id, salida.get("t"))
    if not plan:
        return False
    salida["plan"] = plan
    # Las recomendaciones del motor son de Abrams: con otro héroe se quitan en vez de
    # mezclar consejos de un héroe con la partida de otro.
    salida["recomendaciones"] = []
    salida["fuente_plan"] = f"camino de {heroe_jugado}"
    estado = dict(salida.get("estado") or {})
    estado["motivo"] = (f"camino observado de {heroe_jugado} "
                        f"(n={plan[0].get('n')})")
    salida["estado"] = estado
    return True


def ruta_heroe(hero_id):
    return os.path.join(RAIZ, "data", "meta", f"{int(hero_id)}-camino.json")


def guardar(hero_id, camino, extra=None):
    datos = dict(camino or {})
    datos["heroe"] = int(hero_id)
    if extra:
        datos.update(extra)
    os.makedirs(os.path.dirname(ruta_heroe(hero_id)), exist_ok=True)
    ruta = ruta_heroe(hero_id)
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    os.replace(temporal, ruta)
    return ruta


def cargar(hero_id):
    try:
        with open(ruta_heroe(hero_id), encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None

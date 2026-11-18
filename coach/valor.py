"""Valor medido de una compra: el puente entre el laboratorio y el panel.

El laboratorio (`herramientas/lab/estimador.py`) escribe `datos/modelo_v2.json` con, por
ítem, su efecto en puntos porcentuales contra la compra alternativa del shortlist, su
intervalo al 90 %, su muestra y su etiqueta de evidencia. Este módulo lo lee en caliente
—una vez, con caché— y expone tres cosas, nada más:

    cargar()            el artefacto, o None si no se puede usar
    evidencia(item_id)  lo que el panel puede enseñar de ese ítem (o nada)
    desempatar(filas)   reordena SOLO cuando dos candidatos ya están empatados

Tres reglas de honestidad, en código:

1. Si falta el artefacto o su `sha256` no corresponde al corpus congelado, no hay
   valores: la app sigue funcionando con la heurística y lo dice. Nunca se inventa un
   número para llenar el hueco.
2. Un ítem con `sin_senal` o con menos de 40 compras no aporta evidencia y no se
   muestra. Mostrar un punto sin intervalo está prohibido por la especificación.
3. No se reordena el ranking: se desempata. El efecto medido es de 1-2 pp con un
   intervalo ancho; usarlo para reescribir el orden sería cambiar una heurística
   medible por otra peor medida. Solo se mueve cuando la diferencia de score ya está
   dentro del margen de empate que el propio motor declara.
"""
from __future__ import annotations

import json
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA = os.path.join(RAIZ, "datos", "modelo_v2.json")
RUTA_CORPUS = os.path.join(RAIZ, "datos", "corpus.json")

_cache = {"ruta": None, "doc": None, "error": None}


def _leer_json(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return None


def cargar(forzar=False):
    """El artefacto validado, o None. Nunca lanza: una caché rota no rompe la app."""
    if not forzar and _cache["ruta"] == RUTA and (
            _cache["doc"] is not None or _cache["error"] is not None):
        return _cache["doc"]
    _cache["ruta"] = RUTA
    _cache["doc"] = None
    _cache["error"] = None
    doc = _leer_json(RUTA)
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), dict):
        _cache["error"] = "sin artefacto del motor v2"
        return None
    congelado = doc.get("corpus")
    actual = _leer_json(RUTA_CORPUS)
    # `isinstance` explícito: un JSON válido pero con la forma equivocada (lista,
    # null, número) hacía lanzar AttributeError y el motor lo tapaba en silencio.
    if not isinstance(congelado, dict) or not isinstance(actual, dict):
        _cache["error"] = "corpus con forma inesperada"
        return None
    if not congelado.get("sha256_db") or not actual.get("sha256_db"):
        _cache["error"] = "hash del corpus ausente"
        return None
    if congelado.get("sha256_db") != actual.get("sha256_db"):
        # El corpus cambió: los números que hay en el artefacto describen otra base.
        # Se dice y no se usa. Es el modo CIEGO de la especificación.
        _cache["error"] = "el corpus no coincide con el artefacto"
        return None
    # El hash de la base no basta: el corpus puede cambiar sin tocar la base (el filtro
    # de partidas completas del 2026-11-18 quitó 2 747 partidas de otro modo). Si los
    # conteos no cuadran, el artefacto describe otro corpus y no se enseña.
    for campo in ("filas", "partidas", "victorias"):
        if congelado.get(campo) != actual.get(campo):
            _cache["error"] = f"el corpus cambió ({campo}) desde el artefacto"
            return None
    _cache["doc"] = doc
    return doc


def modo():
    """'MEDIDO' si hay artefacto válido, 'CIEGO' si no."""
    return "MEDIDO" if cargar() is not None else "CIEGO"


def motivo():
    """Por qué no hay valores, en una línea (para el pie del panel)."""
    return _cache.get("error")


def para(item_id):
    """Entrada cruda del ítem, o None."""
    doc = cargar()
    if not doc:
        return None
    return doc["items"].get(str(item_id))


def evidencia(item_id):
    """Lo que el panel puede enseñar: solo si hay intervalo, muestra y etiqueta útil."""
    datos = para(item_id)
    if not datos:
        return None
    ic = datos.get("ic90")
    etiqueta = datos.get("etiqueta")
    if not isinstance(ic, list) or len(ic) != 2 or not etiqueta:
        return None
    try:
        n = int(datos.get("n"))
        n_partidas = int(datos.get("n_partidas") or 0)
        efecto = float(datos.get("efecto_pp"))
        bajo, alto = float(ic[0]), float(ic[1])
    except (TypeError, ValueError):
        return None
    if n < 40 or etiqueta == "sin_senal":
        return None
    congelado = (cargar() or {}).get("corpus")
    congelado = congelado if isinstance(congelado, dict) else {}
    return {
        "efecto_pp": efecto,
        "ic90": [bajo, alto],
        "n": n,
        "n_partidas": n_partidas,
        "etiqueta": etiqueta,
        "evalue": datos.get("evalue"),
        "mde_pp": datos.get("mde_pp"),
        "parche": str(congelado.get("generado") or "")[:10],
        "fuente": "modelo_v2",
    }


def desempatar(filas, margen):
    """Reordena solo los empates técnicos, por cota inferior del efecto medido.

    `filas` viene ordenada por score del motor. Si la segunda está a menos de `margen`
    puntos de la primera, se mira la cota inferior del efecto (LCB90) y se sube la que
    tenga más respaldo **cuando esa cota es positiva**. Si ninguna la tiene, no se toca
    nada: el empate sigue siendo un empate.

    Devuelve (filas, movido) donde `movido` es None o {de, a, lcb}.
    """
    if not isinstance(filas, list) or len(filas) < 2 or not margen:
        return filas, None
    doc = cargar()
    if not doc:
        return filas, None
    primero, segundo = filas[0], filas[1]
    try:
        if abs(float(primero.get("score") or 0) - float(segundo.get("score") or 0)) > margen:
            return filas, None
    except (TypeError, ValueError):
        return filas, None
    valores = []
    for f in (primero, segundo):
        datos = doc["items"].get(str(f.get("id"))) or {}
        lcb = datos.get("lcb90")
        etiqueta = datos.get("etiqueta")
        if lcb is None or etiqueta in (None, "sin_senal"):
            return filas, None
        try:
            lcb = float(lcb)
            n = int(datos.get("n") or 0)
        except (TypeError, ValueError):
            return filas, None
        # Solo desempata lo que replicó su signo fuera de muestra: un ítem que
        # cambia de signo en partidas que el modelo no vio no puede mandar.
        if datos.get("oos_signo") is not True:
            return filas, None
        valores.append((lcb, n))
    # Solo se cambia el orden si el segundo tiene cota positiva y mejor que el primero.
    if valores[1][0] > valores[0][0] and valores[1][0] > 0:
        cambiadas = [segundo, primero] + list(filas[2:])
        return cambiadas, {"de": primero.get("id"), "a": segundo.get("id"),
                           "lcb": valores[1][0]}
    return filas, None


def preferencia(filas, margen=0.5):
    """¿El modelo prefiere otra compra empatada? Devuelve el aviso, no cambia nada.

    Condiciones, todas obligatorias: la diferencia de score ya es un empate para el
    motor, la alternativa replicó su efecto fuera de muestra, su cota inferior supera
    +0.5 pp y es mejor que la del ítem elegido. Si algo no se cumple, no hay aviso:
    un empate sin evidencia sigue siendo un empate.
    """
    doc = cargar()
    if not doc or not isinstance(filas, list) or len(filas) < 2:
        return None
    try:
        if abs(float(filas[0].get("score") or 0)
               - float(filas[1].get("score") or 0)) > float(margen or 0.5):
            return None
    except (TypeError, ValueError):
        return None
    elegido = doc["items"].get(str(filas[0].get("id"))) or {}
    alterno = doc["items"].get(str(filas[1].get("id"))) or {}
    if alterno.get("oos_signo") is not True:
        return None
    try:
        lcb_alt = float(alterno.get("lcb90"))
        lcb_eleg = float(elegido.get("lcb90")) if elegido.get("lcb90") is not None else 0.0
    except (TypeError, ValueError):
        return None
    if lcb_alt <= 0.5 or lcb_alt <= lcb_eleg:
        return None
    return {
        "id": str(filas[1].get("id")),
        "nombre": filas[1].get("nombre") or alterno.get("nombre"),
        "efecto_pp": alterno.get("efecto_pp"),
        "lcb90": round(lcb_alt, 2),
        "motivo_id": str(filas[0].get("id")),
    }


def comparar(filas, margen=0.5):
    """¿El valor medido elegiría otro ítem? No cambia nada: solo deja constancia.

    Se usa para acumular evidencia de si el modelo v2 acierta antes de darle la
    potestad de reordenar. Devuelve None si coinciden, no hay empate o no hay datos.
    """
    doc = cargar()
    if not doc or not isinstance(filas, list) or len(filas) < 2:
        return None
    try:
        if abs(float(filas[0].get("score") or 0) - float(filas[1].get("score") or 0)) > margen:
            return None
    except (TypeError, ValueError):
        return None
    elegido, alterno = filas[0], filas[1]
    a = (doc["items"].get(str(elegido.get("id"))) or {}).get("lcb90")
    b = (doc["items"].get(str(alterno.get("id"))) or {}).get("lcb90")
    if a is None or b is None:
        return None
    if b > a and b > 0:
        return {"motor": str(elegido.get("id")), "valor": str(alterno.get("id")),
                "lcb_motor": float(a), "lcb_valor": float(b)}
    return None


def resumen():
    """Estado del artefacto para el pie y para el diagnóstico."""
    doc = cargar()
    if not doc:
        return {"modo": "CIEGO", "motivo": motivo()}
    items = doc.get("items")
    items = items if isinstance(items, dict) else {}
    medidos = sum(1 for v in items.values()
                  if isinstance(v, dict) and v.get("etiqueta") == "medido")
    return {
        "modo": "MEDIDO",
        "items": len(items),
        "medidos": medidos,
        "generado": doc.get("generado"),
        "semilla": (doc.get("metodo") or {}).get("semilla"),
        "bootstrap": (doc.get("metodo") or {}).get("bootstrap"),
    }

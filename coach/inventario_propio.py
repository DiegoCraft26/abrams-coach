"""Tu inventario, con procedencia: de dónde salió, cuándo y con cuánta confianza.

El inventario es el dato más caro de conseguir y el más fácil de estropear: si se lee de
la vista de un jugador espectado, o de una tienda a medias, el motor recomienda sobre una
partida que no es la tuya. Por eso cada lectura guarda su fuente, su hora y su confianza,
y aquí se aplican las reglas del relevo del 2026-11-09:

- si `espectando` es true, **no se actualiza** nada;
- solo cuenta lo que venga de la tienda propia o de una lectura sin espectar;
- si la última lectura tiene más de 3 min, se avisa «abre B un segundo» en vez de dar por
  bueno un inventario viejo;
- lo que se sabe sobrevive a un reinicio del coach (`salida/inventario.json`).
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA = os.path.join(RAIZ, "salida", "inventario.json")

# Pasado este tiempo el inventario no se usa para decidir: se muestra con su edad.
VIDA_UTIL_S = 180.0
# Y a partir de aquí se le pide a Diego que abra la tienda un segundo.
AVISO_S = 180.0

_LOCK = threading.Lock()
_ESTADO: dict | None = None
_CARGADO = False


def _leer_disco() -> dict | None:
    try:
        with open(RUTA, encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return datos if isinstance(datos, dict) else None


def _asegurar_cargado():
    global _ESTADO, _CARGADO
    if not _CARGADO:
        _ESTADO = _leer_disco()
        _CARGADO = True


def reiniciar_para_pruebas():
    """Solo para tests: olvida lo cargado y lo guardado."""
    global _ESTADO, _CARGADO
    with _LOCK:
        _ESTADO = None
        _CARGADO = False


def actualizar(items, slots=None, fuente: str = "tienda", confianza: float = 0.0,
               espectando: bool = False, ts: float | None = None,
               ruta: str | None = None) -> bool:
    """Guarda una lectura del inventario propio. Devuelve False si no se aceptó.

    La guardia de espectador es lo primero: mirar la partida de otro no puede cambiar tu
    inventario. Después, una tienda abierta es la fuente buena; lo demás se acepta pero
    queda marcado para que quien lea sepa cuánto fiarse.
    """
    global _ESTADO
    if espectando:
        return False
    if not items and not slots:
        return False
    limpio = [str(i) for i in items if str(i).isdigit()]
    contados = {}
    for clave in ("weapon", "vitality", "spirit"):
        valor = (slots or {}).get(clave)
        if isinstance(valor, dict):
            valor = valor.get("usados", valor.get("n"))
        try:
            numero = int(valor)
        except (TypeError, ValueError):
            continue
        if 0 <= numero <= 6:
            contados[clave] = numero
    nuevo = {
        "items": limpio,
        "slots": contados,
        "fuente": fuente,
        "confianza": round(float(confianza or 0.0), 2),
        "ts": float(ts or time.time()),
    }
    with _LOCK:
        _asegurar_cargado()
        _ESTADO = nuevo
    _guardar(nuevo, ruta)
    return True


def _guardar(datos: dict, ruta: str | None = None):
    destino = ruta or RUTA
    carpeta = os.path.dirname(destino)
    try:
        os.makedirs(carpeta, exist_ok=True)
        texto = json.dumps(datos, ensure_ascii=False, indent=1)
        with tempfile.NamedTemporaryFile("w", dir=carpeta, prefix=".inv-",
                                         suffix=".tmp", delete=False,
                                         encoding="utf-8") as f:
            f.write(texto)
            temporal = f.name
        os.replace(temporal, destino)
    except OSError:
        pass


def leer(max_edad_s: float = VIDA_UTIL_S, ruta: str | None = None) -> dict | None:
    """El inventario si sigue siendo utilizable; si no, None.

    Devuelve copia con `edad_s` para que quien pinte pueda decirlo sin calcular nada.
    """
    with _LOCK:
        _asegurar_cargado()
        datos = dict(_ESTADO) if _ESTADO else None
    if datos is None and ruta:
        datos = _leer_disco() if ruta == RUTA else None
    if not datos:
        return None
    edad = max(0.0, time.time() - float(datos.get("ts") or 0))
    if edad > max_edad_s:
        return None
    salida = dict(datos)
    salida["edad_s"] = round(edad, 1)
    salida["items"] = list(datos.get("items") or [])
    salida["slots"] = dict(datos.get("slots") or {})
    return salida


def como_estado(ruta: str | None = None) -> dict | None:
    """Lo que espera el panel: `inventario` arriba y los huecos por categoría.

    Misma forma que lo que publica el broadcast, para que el panel no sepa de dónde
    viene: si viene de una tienda leída por visión, lo dice en las notas.
    """
    datos = leer(ruta=ruta)
    if datos is None:
        return None
    slots = {}
    for clave, usados in (datos.get("slots") or {}).items():
        slots[clave] = {"usados": usados, "total": 4}
    return {
        "inventario": [{"id": iid} for iid in datos["items"]],
        "slots": slots,
        "fuente": datos.get("fuente"),
        "confianza": datos.get("confianza"),
        "edad_s": datos.get("edad_s"),
    }


def estado(ruta: str | None = None) -> dict:
    """Resumen honesto para /api/vision y /api/revisar."""
    with _LOCK:
        _asegurar_cargado()
        datos = dict(_ESTADO) if _ESTADO else None
    if not datos:
        return {"hay": False, "aviso": "sin lectura todavía"}
    edad = max(0.0, time.time() - float(datos.get("ts") or 0))
    return {
        "hay": True,
        "items": len(datos.get("items") or []),
        "slots": datos.get("slots") or {},
        "fuente": datos.get("fuente"),
        "confianza": datos.get("confianza"),
        "edad_s": round(edad, 1),
        "utilizable": edad <= VIDA_UTIL_S,
        "aviso": ("abre la tienda (B) un segundo" if edad > AVISO_S else None),
    }

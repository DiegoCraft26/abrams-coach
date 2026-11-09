"""Lectura de la tienda: de los nombres que se ven a los ids del catálogo.

El HUD no lleva los ítems: solo la tienda abierta (B) los muestra todos. Y el modelo, con
un recorte de la tienda, lee **nombres** («Restorative Shot»), no ids numéricos: pedirle
ids es pedirle que se los invente.

Así que aquí se hace lo único honesto: el modelo transcribe nombres, y la traducción a id
se hace en local contra `data/catalogo.json`. Un nombre que no esté en el catálogo no se
adivina, se descarta y se anota.

Medido el 2026-11-09: el recorte central del juego pesa 26.6 kB a tamaño nativo; a 640 px
de ancho baja a ~15 kB, que es el tamaño con el que la API sí contesta.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

# La tienda ocupa el centro de la pantalla. El recorte deja fuera el HUD y el minimapa:
# lo que importa son los iconos y los nombres de los ítems.
ZONA_TIENDA = (0.18, 0.12, 0.64, 0.76)
ANCHO = 640
CALIDAD = 72

SISTEMA = """Lees la pantalla de la tienda de Deadlock. Devuelves SOLO un objeto JSON, sin
explicaciones ni markdown. No inventes nombres: si un ítem no se lee, no lo pongas."""

PREGUNTA = """¿Está abierta la tienda de Deadlock? Si lo está, separa dos cosas:

- TUS ÍTEMS: solo los que TÚ llevas ya comprados. En la tienda aparecen en tu fila de
  arriba (los huecos vacíos no cuentan).
- LO QUE SE VENDE: los ítems de la tienda, que son para comprar y no son tuyos.

Transcribe los NOMBRES tal como están escritos. No inventes ninguno.

Devuelve exactamente:
{"tienda_abierta": true|false,
 "mios": ["Nombre exacto de un ítem tuyo"],
 "se_venden": ["Nombre exacto de un ítem en venta"],
 "categoria": "arma|vitalidad|espíritu|null"}"""


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y sin signos: así «Restorative Shot.» casa con el catálogo."""
    if not isinstance(texto, str):
        return ""
    sin_acentos = unicodedata.normalize("NFKD", texto)
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    limpio = re.sub(r"[^a-z0-9 ]+", " ", sin_acentos.lower())
    return re.sub(r"\s+", " ", limpio).strip()


def indice(catalogo: dict | None = None, solo_comprables: bool = True) -> dict:
    """Nombre normalizado → id. Los ítems comprables primero; si no, todos."""
    from . import vision

    catalogo = catalogo if catalogo is not None else vision.catalogo()
    comprables, todos = {}, {}
    for iid, datos in (catalogo or {}).items():
        if not isinstance(datos, dict):
            continue
        clave = normalizar(datos.get("nombre") or "")
        if not clave:
            continue
        todos.setdefault(clave, str(iid))
        if datos.get("comprable", True):
            comprables.setdefault(clave, str(iid))
    if solo_comprables and comprables:
        return comprables
    return todos


def resolver(nombre: str, tabla: dict | None = None, corte: float = 0.82) -> str | None:
    """Nombre del modelo → id del catálogo, o None si no hay nada razonablemente igual.

    Tres intentos, de más a menos estricto: exacto, contenido y parecido. Nada de
    «el más parecido aunque sea otro ítem»: recomendar el ítem equivocado cuesta 800
    almas y la confianza en la app.
    """
    tabla = tabla if tabla is not None else indice()
    clave = normalizar(nombre)
    if not clave:
        return None
    if clave in tabla:
        return tabla[clave]
    # «Restorative» sin la segunda palabra, o «Restorative Shot (componente)».
    for candidato, iid in tabla.items():
        if clave == candidato or clave in candidato.split() or candidato in clave:
            if len(clave) >= 4 and (clave in candidato or candidato in clave):
                return iid
    parecido = difflib.get_close_matches(clave, list(tabla), n=1, cutoff=corte)
    return tabla[parecido[0]] if parecido else None


def resolver_lista(nombres, tabla: dict | None = None) -> tuple[list[str], list[str]]:
    """(ids resueltos sin repetir, nombres que no se pudieron resolver)."""
    tabla = tabla if tabla is not None else indice()
    ids, sobran = [], []
    for nombre in nombres or []:
        if isinstance(nombre, dict):
            nombre = nombre.get("nombre") or nombre.get("name")
        iid = resolver(nombre, tabla)
        if iid is None:
            if nombre:
                sobran.append(str(nombre)[:40])
            continue
        if iid not in ids:
            ids.append(iid)
    return ids, sobran


def recorte_tienda(cuadro, juego, ancho: int = ANCHO):
    """El centro de la pantalla, reducido: donde vive la tienda."""
    jx, jy, jw, jh = juego
    x, y, w, h = ZONA_TIENDA
    caja = (jx + int(x * jw), jy + int(y * jh), int(w * jw), int(h * jh))
    recorte = cuadro.crop((caja[0], caja[1], caja[0] + caja[2], caja[1] + caja[3]))
    if ancho and recorte.width > ancho:
        alto = max(1, int(recorte.height * ancho / recorte.width))
        recorte = recorte.resize((ancho, alto))
    return recorte


def imagen_tienda(cuadro, juego, ancho: int = ANCHO, calidad: int = CALIDAD) -> bytes:
    import io

    recorte = recorte_tienda(cuadro, juego, ancho)
    salida = io.BytesIO()
    recorte.convert("RGB").save(salida, format="JPEG", quality=calidad, optimize=True)
    return salida.getvalue()


def normalizar_respuesta(datos, tabla: dict | None = None) -> dict:
    """Del JSON del modelo (nombres) al estado que usa la app (ids)."""
    tabla = tabla if tabla is not None else indice()
    if not isinstance(datos, dict):
        return {"tienda_abierta": False, "items": [], "no_resueltos": []}
    abierta = datos.get("tienda_abierta")
    if isinstance(abierta, str):
        abierta = abierta.strip().lower() in ("true", "si", "sí", "1")
    # `mios` es lo que el jugador lleva; `se_venden` es el catálogo de la tienda. Antes
    # se pedía una sola lista y el modelo devolvía los 10 componentes en venta como si
    # fueran el inventario de Diego (visto el 2026-11-09).
    nombres = datos.get("mios")
    if nombres is None:
        nombres = datos.get("items") or []
    if not isinstance(nombres, list):
        nombres = []
    en_venta = datos.get("se_venden") or []
    if not isinstance(en_venta, list):
        en_venta = []
    ids, sobran = resolver_lista(nombres[:14], tabla)
    ids_venta, _ = resolver_lista(en_venta[:24], tabla)
    categoria = str(datos.get("categoria") or "").strip().lower()
    return {
        "tienda_abierta": bool(abierta) and bool(ids or nombres or ids_venta),
        "items": ids,
        "se_venden": ids_venta,
        "no_resueltos": sobran,
        "categoria": categoria if categoria in ("arma", "vitalidad", "espíritu",
                                                "weapon", "vitality", "spirit") else None,
    }


def leer_jpeg(jpeg: bytes, proveedor, timeout_s: float = 35.0) -> dict | None:
    """Lee un recorte de tienda ya codificado. None si no hubo respuesta."""
    from . import vision

    try:
        respuesta = proveedor.chat_vision(jpeg, PREGUNTA, sistema=SISTEMA,
                                          timeout_s=timeout_s)
        crudo = vision._extraer_json(vision.contenido(respuesta))
    except Exception:                                     # noqa: BLE001
        return None
    datos = normalizar_respuesta(crudo)
    datos["fase"] = "en_partida"
    datos["_peso_kb"] = round(len(jpeg) / 1024, 1)
    datos["_tokens"] = (respuesta.get("usage") or {}).get("total_tokens")
    return datos


def leer(cuadro, juego, proveedor, timeout_s: float = 35.0) -> dict | None:
    return leer_jpeg(imagen_tienda(cuadro, juego), proveedor, timeout_s=timeout_s)

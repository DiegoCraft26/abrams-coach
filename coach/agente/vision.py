"""Visión bajo demanda: un cuadro de Deadlock se convierte en un estado en JSON.

Reglas que salieron del relevo del 2026-11-09 y que este módulo hace cumplir:

- **Un cuadro no se paga dos veces.** La caché va por hash del JPEG: el reloj cambia una
  vez por segundo, así que dos lecturas del mismo cuadro devuelven lo mismo sin llamar.
- **Tope por partida** (300 cuadros), con aviso al 70 %. Sin tope, un bucle nervioso
  puede vaciar el presupuesto en una tarde.
- **Si la API falla o tarda, se devuelve None.** El llamante conserva el último estado y
  le pone la edad. Nunca se inventa una compra.
- **Los ids que no existen en `data/catalogo.json` se descartan.** Un modelo alucinando
  un id de ítem es el error más caro: la recomendación sale y nadie la puede comprar.
- **Nada de OCR para el camino principal:** el reloj de respaldo sigue siendo el del HUD,
  pero el inventario y la tienda salen de aquí.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUTA_CATALOGO = os.path.join(RAIZ, "data", "catalogo.json")

# Medido el 2026-11-09 con la API real (ver `docs/vision-mediciones.md`): por encima de
# ~40 kB de JPEG las peticiones se caen por tiempo de espera, y a 33 kB la respuesta llega
# en ~23 s. Se manda el recorte del monitor del juego a 640 px: se lee el reloj, el oro y
# la tienda. Un cuadro completo del escritorio no cabe en el tiempo de nadie.
LADO_MAX = 640
CALIDAD_JPEG = 70

# Lo que tarda de verdad una lectura de 640 px. El tope de 8 s del relevo se rompía con
# cualquier cuadro real; con 30 s entra y el que espera es un hilo, nunca el panel.
TIMEOUT_S = 30.0

# Tope por partida y aviso. 300 cuadros a 1 cada 5 s cubren 25 min, que es una partida
# larga; el aviso al 70 % deja margen para bajar el ritmo antes de quedarse sin visión.
TOPE_PARTIDA = 300
AVISO_70 = 0.7

SISTEMA = """Eres un lector de pantalla del juego Deadlock. Recibes un cuadro y devuelves SOLO
un objeto JSON válido, sin explicaciones, sin markdown y sin texto antes ni después.

Reglas, en orden de importancia:
1. No inventes. Si un campo no se ve con claridad, pon null. Un null es correcto; un
   número inventado estropea la decisión de compra.
2. La tienda abierta (tecla B) es la única fuente fiable de tus 12 ítems. Si la tienda
   no está abierta, `items` va vacío y `tienda_abierta` es false.
3. El marcador (Tab) da almas, KDA y héroes de los dos equipos; no da ítems.
4. Si `espectando` es true, no estás viendo tu propia partida: no rellenes `items` ni
   `slots` propios.
5. `reloj_s` en segundos desde el inicio de la partida tal como lo marca el HUD.
6. `oro` es el dinero sin gastar y `almas` el total de la partida (el número grande).
7. Los ítems van por su `id` numérico de Deadlock, no por nombre.
8. `confianza` entre 0 y 1: baja si el cuadro está borroso, cortado o a media transición.

Esquema exacto de salida:
{"fase": "menu|hideout|queue|pregame|en_partida|postpartida|espectando|desconocida",
 "en_partida": true, "espectando": false, "heroe": "abrams|null",
 "reloj_s": 423, "oro": 1200, "almas": 7600,
 "tienda_abierta": false, "marcador_abierto": false,
 "items": ["1548066885"], "slots": {"weapon": 3, "vitality": 4, "spirit": 2},
 "enemigos": [{"heroe": "haze", "almas": 8000, "bajadas": 2, "muertes": 1}],
 "huevo": {"tiene": true, "desde_s": 300, "almas_estimadas": 400},
 "confianza": 0.82, "notas": "texto corto"}
"""

FASES = {"menu", "hideout", "queue", "pregame", "en_partida", "postpartida",
         "espectando", "desconocida"}
SLOTS = ("weapon", "vitality", "spirit")

_CATALOGO: dict | None = None
_LOCK = threading.Lock()


# ---------------------------------------------------------------- imágenes
def cuadro_a_jpeg(cuadro, lado_max: int = LADO_MAX, calidad: int = CALIDAD_JPEG) -> bytes:
    """Convierte un cuadro (PIL, ruta o bytes PNG) en el JPEG que se manda.

    Se baja a 1280 de lado mayor: el modelo no necesita más para leer la tienda y cada
    píxel de más se paga en tokens y en latencia.
    """
    from PIL import Image

    if isinstance(cuadro, (bytes, bytearray)):
        imagen = Image.open(io.BytesIO(cuadro))
    elif isinstance(cuadro, str):
        imagen = Image.open(cuadro)
    else:
        imagen = cuadro
    imagen = imagen.convert("RGB")
    ancho, alto = imagen.size
    escala = min(1.0, lado_max / max(ancho, alto))
    if escala < 1.0:
        imagen = imagen.resize((max(1, int(ancho * escala)), max(1, int(alto * escala))))
    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", quality=calidad, optimize=True)
    return salida.getvalue()


def recorte_juego(cuadro, caja=None):
    """Recorta el monitor del juego del cuadro completo del escritorio.

    `caja` es (x, y, ancho, alto) en píxeles del escritorio. Sin caja, devuelve el cuadro
    tal cual: quien llama sabe dónde está su juego mejor que este módulo.
    """
    if caja is None:
        return cuadro
    try:
        x, y, ancho, alto = (int(v) for v in caja)
    except (TypeError, ValueError):
        return cuadro
    if ancho <= 0 or alto <= 0:
        return cuadro
    try:
        return cuadro.crop((x, y, x + ancho, y + alto))
    except Exception:                                     # noqa: BLE001
        return cuadro


def hash_cuadro(jpeg: bytes) -> str:
    return hashlib.blake2b(jpeg, digest_size=16).hexdigest()


# ---------------------------------------------------------------- catálogo
def catalogo() -> dict:
    """Id → ítem, cargado una vez. Si falta el archivo, dict vacío (no se filtra nada)."""
    global _CATALOGO
    with _LOCK:
        if _CATALOGO is None:
            try:
                with open(RUTA_CATALOGO, encoding="utf-8") as f:
                    _CATALOGO = json.load(f)
            except (OSError, json.JSONDecodeError):
                _CATALOGO = {}
        return _CATALOGO


def _id_valido(valor) -> str | None:
    texto = str(valor).strip()
    if texto.isdigit() and texto in catalogo():
        return texto
    return None


# ---------------------------------------------------------------- validación
def _numero(valor, minimo=None, maximo=None, entero=False):
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        numero = float(valor) if not entero else int(float(valor))
    except (TypeError, ValueError):
        return None
    if minimo is not None and numero < minimo:
        return None
    if maximo is not None and numero > maximo:
        return None
    return numero


def _booleano(valor) -> bool:
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        return valor.strip().lower() in ("true", "sí", "si", "1")
    return bool(valor) if isinstance(valor, (int, float)) else False


def normalizar(datos) -> dict:
    """Deja el JSON del modelo en algo que el motor pueda usar sin defenderse.

    Lo que no se puede comprobar se pone a None o se descarta; lo que el modelo inventa
    (ids fuera de catálogo, fases raras, confianzas imposibles) no pasa.
    """
    if not isinstance(datos, dict):
        raise ValueError("la respuesta no es un objeto JSON")
    fase = str(datos.get("fase") or "").strip().lower()
    limpio = {
        "fase": fase if fase in FASES else "desconocida",
        "en_partida": _booleano(datos.get("en_partida")),
        "espectando": _booleano(datos.get("espectando")),
        "heroe": None,
        "reloj_s": _numero(datos.get("reloj_s"), 0, 4 * 3600, entero=True),
        "oro": _numero(datos.get("oro"), 0, 200_000, entero=True),
        "almas": _numero(datos.get("almas"), 0, 500_000, entero=True),
        "tienda_abierta": _booleano(datos.get("tienda_abierta")),
        "marcador_abierto": _booleano(datos.get("marcador_abierto")),
        "items": [],
        "slots": {},
        "enemigos": [],
        "huevo": None,
        "confianza": _numero(datos.get("confianza"), 0.0, 1.0) or 0.0,
        "notas": str(datos.get("notas") or "")[:200],
    }
    heroe = datos.get("heroe")
    if isinstance(heroe, str) and re.fullmatch(r"[a-z_]{2,20}", heroe.strip().lower()):
        limpio["heroe"] = heroe.strip().lower()

    # Ítems: solo ids que existan de verdad en el catálogo, sin repetir.
    vistos = set()
    for bruto in datos.get("items") or []:
        if isinstance(bruto, dict):
            bruto = bruto.get("id")
        iid = _id_valido(bruto)
        if iid and iid not in vistos:
            vistos.add(iid)
            limpio["items"].append(iid)

    for slot in SLOTS:
        valor = (datos.get("slots") or {}).get(slot) if isinstance(
            datos.get("slots"), dict) else None
        numero = _numero(valor, 0, 6, entero=True)
        if numero is not None:
            limpio["slots"][slot] = numero

    for enemigo in (datos.get("enemigos") or [])[:6]:
        if not isinstance(enemigo, dict):
            continue
        nombre = str(enemigo.get("heroe") or "").strip().lower()
        if not re.fullmatch(r"[a-z_]{2,20}", nombre):
            continue
        limpio["enemigos"].append({
            "heroe": nombre,
            "almas": _numero(enemigo.get("almas"), 0, 500_000, entero=True),
            "bajadas": _numero(enemigo.get("bajadas"), 0, 99, entero=True),
            "muertes": _numero(enemigo.get("muertes"), 0, 99, entero=True),
        })

    huevo = datos.get("huevo")
    if isinstance(huevo, dict) and _booleano(huevo.get("tiene")):
        limpio["huevo"] = {
            "tiene": True,
            "desde_s": _numero(huevo.get("desde_s"), 0, 4 * 3600, entero=True),
            "almas_estimadas": _numero(huevo.get("almas_estimadas"), 0, 100_000,
                                       entero=True),
        }
    return limpio


def _extraer_json(texto: str) -> dict:
    """Saca el objeto JSON de la respuesta, aunque venga con ```json o con prosa."""
    limpio = (texto or "").strip()
    limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", limpio, flags=re.IGNORECASE)
    try:
        return json.loads(limpio)
    except json.JSONDecodeError:
        pass
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    if inicio >= 0 and fin > inicio:
        return json.loads(limpio[inicio:fin + 1])
    raise ValueError("no hay JSON en la respuesta")


def contenido(respuesta: dict) -> str:
    """Texto del primer mensaje del proveedor, en formato OpenAI."""
    opciones = respuesta.get("choices") or []
    if not opciones:
        raise ValueError("respuesta sin choices")
    mensaje = opciones[0].get("message") or {}
    return mensaje.get("content") or ""


def tokens(respuesta: dict) -> int | None:
    uso = respuesta.get("usage") or {}
    valor = uso.get("total_tokens") or uso.get("prompt_tokens")
    return int(valor) if isinstance(valor, (int, float)) else None


# ---------------------------------------------------------------- tope por partida
class TopePartida:
    """Cuenta los cuadros de la partida en curso y avisa al 70 %."""

    def __init__(self, tope: int = TOPE_PARTIDA, aviso: float = AVISO_70):
        self.tope = tope
        self.aviso = aviso
        self._lock = threading.Lock()
        self._gastados = 0
        self._avisado = False
        self._tokens = 0
        self._fallos = 0

    def reiniciar(self):
        with self._lock:
            self._gastados = 0
            self._avisado = False
            self._tokens = 0
            self._fallos = 0

    def puede(self) -> bool:
        with self._lock:
            return self._gastados < self.tope

    def gastar(self, tokens_usados: int | None = None, fallo: bool = False) -> dict:
        with self._lock:
            self._gastados += 1
            if tokens_usados:
                self._tokens += int(tokens_usados)
            if fallo:
                self._fallos += 1
            aviso_ahora = (not self._avisado
                           and self._gastados >= self.tope * self.aviso)
            if aviso_ahora:
                self._avisado = True
            return {"avisar_70": aviso_ahora, "gastados": self._gastados}

    def estado(self) -> dict:
        with self._lock:
            return {"cuadros": self._gastados, "tope": self.tope,
                    "tokens": self._tokens, "fallos": self._fallos,
                    "restantes": max(0, self.tope - self._gastados)}


TOPE = TopePartida()


# ---------------------------------------------------------------- interpretación
_CACHE: dict[str, dict] = {}
_CACHE_LOCK = threading.Lock()
CACHE_MAX = 240


def _cache_leer(clave: str):
    with _CACHE_LOCK:
        return _CACHE.get(clave)


def _cache_guardar(clave: str, valor: dict):
    with _CACHE_LOCK:
        if len(_CACHE) > CACHE_MAX:
            _CACHE.clear()
        _CACHE[clave] = valor


def contexto_texto(contexto: dict | None) -> str:
    """Lo que ya se sabe, para no pedirle al modelo que lo adivine otra vez."""
    if not contexto:
        return ""
    piezas = []
    for clave in ("fase_log", "heroe", "reloj_s", "oro", "almas", "items", "espectando"):
        valor = contexto.get(clave)
        if valor not in (None, "", [], {}):
            piezas.append(f"{clave}={valor}")
    return ("\nContexto ya conocido (confírmalo o corrígelo, no lo inventes): "
            + ", ".join(piezas)) if piezas else ""


def interpretar(imagen, contexto: dict | None = None, proveedor=None,
                timeout_s: float = TIMEOUT_S, usar_cache: bool = True,
                tope: TopePartida | None = None) -> dict | None:
    """Un cuadro → estado normalizado, o None si no se pudo.

    Devuelve también `_latencia_s`, `_cache` y `_tokens` como metadatos: el panel los
    enseña y las pruebas los miden. Nunca lanza por fallo del proveedor.
    """
    from ..agente import proveedor as P

    jpeg = cuadro_a_jpeg(imagen) if not isinstance(imagen, (bytes, bytearray)) else imagen
    clave = hash_cuadro(jpeg)
    if usar_cache:
        guardado = _cache_leer(clave)
        if guardado is not None:
            return dict(guardado, _cache=True, _latencia_s=0.0)

    tope = tope or TOPE
    if not tope.puede():
        return None
    if proveedor is None:
        proveedor = P.cadena_por_defecto()[0]
    if not P.soporta_vision(proveedor):
        return None
    if not getattr(proveedor, "hay_clave", lambda: True)():
        return None

    texto = "Lee este cuadro de Deadlock y devuelve el JSON." + contexto_texto(contexto)
    inicio = time.perf_counter()
    try:
        respuesta = proveedor.chat_vision(jpeg, texto, sistema=SISTEMA,
                                          timeout_s=timeout_s)
        datos = normalizar(_extraer_json(contenido(respuesta)))
    except Exception:                                     # noqa: BLE001
        tope.gastar(fallo=True)
        return None
    latencia = round(time.perf_counter() - inicio, 3)
    gastados = tokens(respuesta)
    tope.gastar(gastados)
    datos["_latencia_s"] = latencia
    datos["_cache"] = False
    datos["_tokens"] = gastados
    if usar_cache:
        _cache_guardar(clave, datos)
    return datos


def estado() -> dict:
    """Resumen para /api/revisar y para el panel: sin secretos, sin imágenes."""
    return {"tope": TOPE.estado(), "cache": len(_CACHE), "modelo": "visión"}

"""Proveedores LLM compatibles con OpenAI, con respaldo y sin fugas de claves.

Dato crítico verificado el 2026-11-07: la API de Command Code devuelve 403 si
la petición no lleva cabecera `User-Agent`. Con `User-Agent: abrams-coach/1.0`
y `Authorization: Bearer <clave>` responde 200. Todo va por urllib (stdlib).
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol, runtime_checkable

AGENTE_USUARIO = "abrams-coach/1.0"


def _ruta_credenciales() -> Path:
    """Dónde buscar las claves del informe opcional.

    `ABRAMS_CREDENCIALES` manda. Si no, `~/.config/abrams-coach/credenciales.yaml`.
    Se conserva la ruta vieja de la máquina de desarrollo como último recurso.
    """
    elegida = os.environ.get("ABRAMS_CREDENCIALES")
    if elegida:
        return Path(elegida).expanduser()
    nueva = Path.home() / ".config" / "abrams-coach" / "credenciales.yaml"
    if nueva.exists():
        return nueva
    vieja = Path.home() / ".dsh" / ".credentials.yaml"
    return vieja if vieja.exists() else nueva


RUTA_CREDENCIALES = _ruta_credenciales()


class ErrorProveedor(Exception):
    """Un proveedor falló de forma tipificada (red, HTTP, JSON o sin clave)."""


@runtime_checkable
class ProveedorLLM(Protocol):
    """Interfaz mínima de cualquier proveedor de chat."""

    def chat(self, mensajes: list[dict], herramientas: list[dict] | None = None,
             timeout_s: float = 45) -> dict: ...


def soporta_vision(prov) -> bool:
    """¿Ese proveedor puede leer imágenes?

    Va aparte del protocolo a propósito: el modelo local no ve y aun así sirve para el
    informe de partida. Quien manda una captura tiene que preguntarlo antes.
    """
    return callable(getattr(prov, "chat_vision", None))


def leer_credencial(nombre: str) -> str | None:
    """Lee una clave de la sección `refs` del archivo de credenciales.

    Parseo por líneas sin dependencias. El valor nunca se imprime ni se
    loguea: solo se devuelve. Si el archivo o la entrada no existen, None.
    """
    try:
        with open(RUTA_CREDENCIALES, encoding="utf-8") as f:
            lineas = f.read().splitlines()
    except OSError:
        return None
    en_refs = False
    for linea in lineas:
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        # Una clave al mismo nivel que `refs` cierra la sección.
        if not linea.startswith((" ", "\t")):
            en_refs = linea.strip().rstrip(":") == "refs"
            continue
        if not en_refs:
            continue
        clave, _, valor = linea.strip().partition(":")
        if clave.strip() == nombre:
            valor = valor.strip().strip('"').strip("'")
            return valor or None
    return None


class ProveedorOpenAICompatible:
    """Proveedor en formato OpenAI (chat completions) sobre urllib.

    `clave_env` es el nombre de la variable de entorno / credencial (ver
    `leer_credencial`); el valor nunca aparece en mensajes de error.
    """

    def __init__(self, base_url: str, modelo: str, clave_env: str, nombre: str,
                 soporta_herramientas: bool = True, parametros_extra: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.modelo = modelo
        self.clave_env = clave_env
        self.nombre = nombre
        # El Qwen local (llama-server) devuelve HTTP 500 si se le manda el bloque
        # `tools`: verificado el 2026-11-07. Como último recurso responde sin
        # herramientas, con el resumen de estado que ya va en el prompt.
        self.soporta_herramientas = soporta_herramientas
        # El Qwen local razona antes de contestar si no se le apaga: con "thinking"
        # tarda más de 45 s y el respaldo no sirve de nada.
        self.parametros_extra = dict(parametros_extra or {})

    def _clave(self) -> str | None:
        clave = os.environ.get(self.clave_env)
        if clave:
            return clave
        return leer_credencial(self.clave_env)

    def hay_clave(self) -> bool:
        """¿Hay credencial? Solo dice si existe: nunca la devuelve ni la imprime."""
        return bool(self._clave())

    def _intentar(self, mensajes, herramientas, timeout_s):
        clave = self._clave()
        if not clave:
            raise ErrorProveedor(f"{self.nombre}: falta credencial {self.clave_env}")
        cuerpo = {"model": self.modelo, "messages": mensajes}
        cuerpo.update(self.parametros_extra)
        if herramientas and self.soporta_herramientas:
            cuerpo["tools"] = herramientas
        peticion = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(cuerpo, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                # Sin esto, Command Code devuelve 403 (verificado 2026-11-07).
                "User-Agent": AGENTE_USUARIO,
                "Authorization": "Bearer " + clave,
            },
        )
        try:
            with urllib.request.urlopen(peticion, timeout=timeout_s) as respuesta:
                texto = respuesta.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise ErrorProveedor(
                f"{self.nombre}: HTTP {exc.code} de {self.modelo}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise ErrorProveedor(f"{self.nombre}: error de red en {self.modelo}") from exc
        try:
            return json.loads(texto)
        except ValueError as exc:
            raise ErrorProveedor(f"{self.nombre}: respuesta no es JSON") from exc

    def chat(self, mensajes: list[dict], herramientas: list[dict] | None = None,
             timeout_s: float = 45, reintentos: int = 1) -> dict:
        """Una llamada con 1 reintento tras 1 s de espera (configurable)."""
        try:
            return self._intentar(mensajes, herramientas, timeout_s)
        except ErrorProveedor as primero:
            # Sin credencial no hay nada que reintentar: conviene fallar ya.
            if reintentos <= 0 or "falta credencial" in str(primero):
                raise
            time.sleep(1.0)
            return self._intentar(mensajes, herramientas, timeout_s)


    def chat_vision(self, imagen: bytes, texto: str, sistema: str | None = None,
                    timeout_s: float = 30.0, tipo: str = "image/jpeg",
                    reintentos: int = 0) -> dict:
        """Una llamada con imagen (content array de OpenAI + data URL).

        No hay cadena de respaldo aquí: quién la usa decide a qué modelo manda una
        captura de la partida. El reintento es el mismo que `chat`: uno, tras 1 s.
        """
        if not imagen:
            raise ErrorProveedor(f"{self.nombre}: imagen vacía")
        datos = base64.b64encode(imagen).decode("ascii")
        mensajes: list[dict] = []
        if sistema:
            mensajes.append({"role": "system", "content": sistema})
        mensajes.append({"role": "user", "content": [
            {"type": "text", "text": texto},
            {"type": "image_url",
             "image_url": {"url": f"data:{tipo};base64,{datos}"}},
        ]})
        # Las herramientas no aplican a una lectura de pantalla y algunos modelos
        # las rechazan junto con una imagen.
        self_sin_tools = self.soporta_herramientas
        try:
            self.soporta_herramientas = False
            # Sin reintento por defecto: una lectura de pantalla tiene respaldo (el
            # último estado con su edad) y reintentar solo alarga la espera.
            return self.chat(mensajes, None, timeout_s=timeout_s, reintentos=reintentos)
        finally:
            self.soporta_herramientas = self_sin_tools


# Orden medido el 2026-11-09 con cuadros de partida reales: huggingface contesta en
# ~23 s con 33 kB; commandcode se cae por tiempo de espera con ese mismo cuadro (solo
# respondió con imágenes de menos de 1 kB). El Qwen local no ve y queda fuera.
ORDEN_VISION = ("huggingface", "commandcode")


def cadena_vision() -> list[ProveedorOpenAICompatible]:
    """Los proveedores que de verdad leen imágenes, en el orden medido."""
    disponibles = {p.nombre: p for p in cadena_por_defecto()}
    return [disponibles[n] for n in ORDEN_VISION if n in disponibles]


class RespaldoVision:
    """Prueba los proveedores de visión en orden: el primero que contesta, gana.

    Se comporta como un proveedor más (`hay_clave` y `chat_vision`), así que la cola no
    sabe si detrás hay uno o tres. Cada uno se intenta una sola vez: la lectura de
    pantalla tiene respaldo (el último estado con su edad).
    """

    def __init__(self, proveedores: list[ProveedorOpenAICompatible] | None = None):
        self.proveedores = proveedores if proveedores is not None else cadena_vision()
        self.ultimo_bueno: str | None = None

    @property
    def nombre(self) -> str:
        return "visión:" + "+".join(p.nombre for p in self.proveedores)

    @property
    def modelo(self) -> str:
        return self.proveedores[0].modelo if self.proveedores else "sin modelo"

    def hay_clave(self) -> bool:
        return any(p.hay_clave() for p in self.proveedores)

    def chat_vision(self, imagen: bytes, texto: str, sistema: str | None = None,
                    timeout_s: float = 30.0, tipo: str = "image/jpeg") -> dict:
        errores = []
        for prov in self.proveedores:
            if not prov.hay_clave():
                continue
            try:
                respuesta = prov.chat_vision(imagen, texto, sistema=sistema,
                                             timeout_s=timeout_s, tipo=tipo,
                                             reintentos=0)
                self.ultimo_bueno = prov.nombre
                return respuesta
            except ErrorProveedor as exc:
                errores.append(str(exc))
        raise ErrorProveedor(
            "visión: ningún proveedor contestó" + (f" ({'; '.join(errores)})" if errores else ""))


def cadena_por_defecto() -> list[ProveedorOpenAICompatible]:
    """Command Code, Hugging Face y, de último, el Qwen local.

    El tercero es el salvavidas gratis: si la cuota o la red fallan, el
    informe de partida se sigue pudiendo generar con el resumen que ya está en la base. Está apagado cuando
    llama-server no corre (el proveedor simplemente falla y se reporta el error).

    Ojo: ese modelo ocupa ~5.4 GB de VRAM, así que **no debe estar levantado mientras
    se juega** (`systemctl --user stop llama-server`).
    """
    return [
        ProveedorOpenAICompatible(
            "https://api.commandcode.ai/provider/v1",
            "deepseek/deepseek-v4.1-flash",
            "COMMAND_CODE_API_KEY",
            "commandcode",
        ),
        ProveedorOpenAICompatible(
            "https://router.huggingface.co/v1",
            "deepseek-ai/DeepSeek-V4.1-Flash",
            "HUGGINGFACE_API_KEY",
            "huggingface",
        ),
        ProveedorOpenAICompatible(
            "http://127.0.0.1:8080/v1",
            "Qwen3.5-9B local",
            "LOCAL_LLAMA_KEY",
            "local-llama",
            soporta_herramientas=False,
            parametros_extra={"chat_template_kwargs": {"enable_thinking": False},
                              "max_tokens": 600},
        ),
    ]


def proveedor_flash() -> ProveedorOpenAICompatible | None:
    """El proveedor de DS 4.1 Flash de la cadena por defecto (Command Code).

    Se usa cuando hace falta una respuesta suelta y no toda la cadena: si no hay
    clave, quien llama lo dice claro en vez de inventar un veredicto.
    """
    for proveedor in cadena_por_defecto():
        if proveedor.nombre == "commandcode":
            return proveedor
    return None


class ProveedorConRespaldo:
    """Prueba la cadena en orden y usa el primer proveedor que responde.

    Nunca lanza: si todos fallan devuelve `{"error": "..."}`. Recuerda el
    último proveedor útil (`ultimo_proveedor`) y el último error
    (`ultimo_error`) para la UI.
    """

    def __init__(self, cadena: list[ProveedorLLM] | None = None):
        self.cadena = list(cadena) if cadena is not None else cadena_por_defecto()
        self.ultimo_proveedor: str | None = None
        self.ultimo_error: str | None = None

    def chat(self, mensajes: list[dict], herramientas: list[dict] | None = None,
             timeout_s: float = 45) -> dict:
        errores = []
        for proveedor in self.cadena:
            try:
                respuesta = proveedor.chat(mensajes, herramientas, timeout_s)
            except ErrorProveedor as exc:
                errores.append(str(exc))
                continue
            except Exception as exc:  # un doble/proveedor roto también es respaldo
                errores.append(f"{type(exc).__name__}: sin detalle")
                continue
            if isinstance(respuesta, dict) and "error" not in respuesta:
                self.ultimo_proveedor = (getattr(proveedor, "nombre", None)
                                         or type(proveedor).__name__)
                self.ultimo_error = None
                return respuesta
            if isinstance(respuesta, dict):
                errores.append(str(respuesta.get("error")))
            else:
                errores.append(f"{type(proveedor).__name__}: respuesta no es dict")
        self.ultimo_error = "; ".join(errores) if errores else "sin proveedores"
        return {"error": self.ultimo_error}

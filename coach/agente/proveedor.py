"""Proveedores LLM compatibles con OpenAI, con respaldo y sin fugas de claves.

Dato crítico verificado el 2026-11-07: la API de Command Code devuelve 403 si
la petición no lleva cabecera `User-Agent`. Con `User-Agent: abrams-coach/1.0`
y `Authorization: Bearer <clave>` responde 200. Todo va por urllib (stdlib).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol, runtime_checkable

AGENTE_USUARIO = "abrams-coach/1.0"
RUTA_CREDENCIALES = Path.home() / ".dsh" / ".credentials.yaml"


class ErrorProveedor(Exception):
    """Un proveedor falló de forma tipificada (red, HTTP, JSON o sin clave)."""


@runtime_checkable
class ProveedorLLM(Protocol):
    """Interfaz mínima de cualquier proveedor de chat."""

    def chat(self, mensajes: list[dict], herramientas: list[dict] | None = None,
             timeout_s: float = 45) -> dict: ...


def leer_credencial(nombre: str) -> str | None:
    """Lee una clave de la sección `refs` de `~/.dsh/.credentials.yaml`.

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
             timeout_s: float = 45) -> dict:
        """Una llamada con 1 reintento tras 1 s de espera."""
        try:
            return self._intentar(mensajes, herramientas, timeout_s)
        except ErrorProveedor as primero:
            # Sin credencial no hay nada que reintentar: conviene fallar ya.
            if "falta credencial" in str(primero):
                raise
            time.sleep(1.0)
            return self._intentar(mensajes, herramientas, timeout_s)


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

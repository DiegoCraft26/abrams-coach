"""Fuente en vivo desde deadlock-api (broadcast de espectador de Valve).

Envuelve coach.en_vivo: detecta la partida activa y traduce el estado del
stream SSE al formato que consume el motor. Nunca lanza desde estado().
"""
from __future__ import annotations

import time
from typing import Any, Callable


class FuenteApiVivo:
    """Lee una partida real por la API pública, sin OCR y sin tocar el juego."""

    nombre = "en_vivo"

    def __init__(
        self,
        match: int | None = None,
        cuenta: int | None = None,
        timeout_s: float = 20.0,
        reintentos: int = 3,
    ):
        self.match = int(match) if match is not None else None
        self.cuenta = int(cuenta) if cuenta is not None else None
        self.timeout_s = float(timeout_s)
        self.reintentos = max(0, int(reintentos))
        self.ultimo_error: str | None = None
        self._escucha = None
        self._match_actual: int | None = None
        self._callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._ultimo_ok = 0.0
        self._arranque_escucha = 0.0

    def _backoffs(self) -> list[float]:
        base = [0.5, 1.0, 2.0]
        if self.reintentos <= 0:
            return []
        return (base + [base[-1]] * max(0, self.reintentos - len(base)))[: self.reintentos]

    def _resolver_match(self) -> int | None:
        if self.match is not None:
            return self.match
        if self.cuenta is None:
            return None
        from coach import en_vivo

        ultimo: Exception | None = None
        intentos = [0.0] + self._backoffs()
        for i, espera in enumerate(intentos):
            if espera:
                time.sleep(espera)
            try:
                encontrado = en_vivo.partida_activa(self.cuenta, timeout=self.timeout_s)
                if encontrado is not None:
                    self.ultimo_error = None
                    return int(encontrado)
                ultimo = None
            except Exception as exc:  # noqa: BLE001
                ultimo = exc
                self.ultimo_error = f"{type(exc).__name__}: {exc}"
        if ultimo is None and self.ultimo_error is None:
            self.ultimo_error = "no hay partida activa"
        return None

    def disponible(self) -> bool:
        if self.match is not None:
            return True
        if self.cuenta is None:
            return False
        try:
            from coach import en_vivo

            return en_vivo.partida_activa(self.cuenta, timeout=self.timeout_s) is not None
        except Exception:
            return False

    def _asegurar_escucha(self, match: int):
        from coach import en_vivo

        if self._escucha is not None and self._match_actual == match:
            if not self._escucha.vivo() and self._escucha.error:
                # El stream murió; se reemplaza para permitir un reintento limpio.
                try:
                    self._escucha.parar(espera=0.5)
                except Exception:
                    pass
                self._escucha = None
            else:
                return self._escucha
        if self._escucha is not None:
            try:
                self._escucha.parar(espera=0.5)
            except Exception:
                pass
        self._escucha = en_vivo.Escucha(
            match,
            cuenta=self.cuenta,
            reintento=1.0,
            tope_reintentos=max(1, self.reintentos),
            max_segundos=None,
        )
        self._escucha.arrancar()
        self._match_actual = match
        self._arranque_escucha = time.time()
        return self._escucha

    def _traducir(self, est: dict[str, Any], escucha=None) -> dict[str, Any]:
        cuenta_txt = str(int(self.cuenta)) if self.cuenta is not None else None
        yo = est.get("yo") or {}

        def limpio(lista: Any) -> list[dict[str, Any]]:
            salida = []
            for j in lista or []:
                if not isinstance(j, dict):
                    continue
                if cuenta_txt is not None and str(j.get("cuenta")) == cuenta_txt:
                    continue
                salida.append(
                    {
                        "heroe": j.get("heroe"),
                        "almas": j.get("almas"),
                        "bajas": j.get("bajas") or 0,
                        "muertes": j.get("muertes") or 0,
                        "asistencias": j.get("asistencias") or 0,
                    }
                )
            return salida

        notas = [
            "almas, héroes y KDA desde el broadcast de espectador "
            "(latencia ~20-25 s del TV de Valve)"
        ]
        if escucha is not None and getattr(escucha, "conectado", False):
            notas.append("stream conectado")
        elif escucha is not None and getattr(escucha, "error", None):
            notas.append(f"error de stream: {escucha.error}")

        return {
            "t": est.get("t") or 0,
            "yo": {
                "heroe": yo.get("heroe"),
                "almas": yo.get("almas"),
                "oro": yo.get("oro"),
                "items": list(yo.get("items") or []),
                "bajas": yo.get("bajas") or 0,
                "muertes": yo.get("muertes") or 0,
                "asistencias": yo.get("asistencias") or 0,
            },
            "aliados": limpio(est.get("aliados") or []),
            "enemigos": limpio(est.get("enemigos") or []),
            "confianza": 0.95,
            "fuente": "en_vivo",
            "notas": notas,
        }

    def estado(self) -> dict[str, Any] | None:
        try:
            match = self._resolver_match()
            if match is None:
                return None
            escucha = self._asegurar_escucha(match)
            # Espera breve con backoff para que llegue el primer estado útil.
            esperas = [0.0] + self._backoffs()
            est = None
            for espera in esperas:
                if espera:
                    time.sleep(espera)
                est = getattr(escucha, "estado", None)
                if est is not None:
                    break
            if est is None:
                self.ultimo_error = getattr(escucha, "error", None) or "sin datos del broadcast"
                # Si la partida terminó (o el demo dejó de existir), el id queda
                # clavado y el coach nunca vuelve a buscar la siguiente. Se suelta
                # el id para reintentar por cuenta; con --match fijo no se toca.
                vivo = True
                try:
                    vivo = bool(escucha.vivo())
                except Exception:                              # noqa: BLE001
                    vivo = False
                ultima_senal = max(self._ultimo_ok, self._arranque_escucha)
                if self.match is None and (not vivo or time.time() - ultima_senal > 90.0):
                    try:
                        escucha.parar(espera=0.5)
                    except Exception:                          # noqa: BLE001
                        pass
                    self._escucha = None
                    self._match_actual = None
                return None
            self._ultimo_ok = time.time()
            traducido = self._traducir(est, escucha=escucha)
            self.ultimo_error = None
            for fn in list(self._callbacks):
                try:
                    fn(traducido)
                except Exception:
                    pass
            return traducido
        except Exception as exc:  # noqa: BLE001
            self.ultimo_error = f"{type(exc).__name__}: {exc}"
            return None

    def suscribir(self, fn: Callable[[dict[str, Any]], None]) -> None:
        if callable(fn):
            self._callbacks.append(fn)

    def cerrar(self) -> None:
        if self._escucha is not None:
            try:
                self._escucha.parar(espera=1.0)
            except Exception:
                pass
        self._escucha = None
        self._match_actual = None
        self._callbacks.clear()

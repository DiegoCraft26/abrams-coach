"""Carga y validación de la configuración del coach (config/coach.yaml)."""
from __future__ import annotations

import json
import os
from typing import Any, Optional


_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RUTA_DEFAULT = os.path.join(_RAIZ, "config", "coach.yaml")


# ------------------------------------------------------------------ defaults
try:
    from . import motor as _motor_mod

    _MOTOR_DEFECTO = dict(getattr(_motor_mod, "CFG_DEFECTO", {}))
except Exception:
    _MOTOR_DEFECTO = {}

if not _MOTOR_DEFECTO:
    _MOTOR_DEFECTO = {
        "slots": {"weapon": 4, "vitality": 4, "spirit": 4},
        "flex": 0,
        "w_lift": 1.0,
        "w_counter": 0.75,
        "w_fase": 0.40,
        "w_precio": 0.20,
        "w_flujo": 0.50,
        "w_cadena": 1.20,
        "w_tiempo": 0.18,
        "w_venta": 1.20,
        "lift_minimo": -0.010,
        "umbral_ventaja": 0.10,
        "fase_minima_s": 600,
        "duracion_tipica_s": 2400,
        "venta_minima_tasa": 0.40,
        "venta_margen_pp": 2.0,
        "ventana_fase": 22.0,
        "venta_margen_s": 60,
    }

_UI_DEFECTO = {
    "ancho": 960,
    "alto": 1080,
    "breakpoints": {"angosto_max": 760, "amplio_min": 1100},
    "angosto_max": 760,
    "amplio_min": 1100,
    "actualizacion_hz": 1,
}

_FUENTES_DEFECTO = {
    "timeout_s": 10,
    "reintentos": 3,
    "backoff_s": 2,
}

_AGENTE_DEFECTO = {
    "modelo": "deepseek/deepseek-v4.1-flash",
    "proveedor": "commandcode",
    "fallback": "huggingface",
    "presupuesto_llamadas_min": 6,
    "presupuesto_llamadas_sesion": 120,
    "cache_s": 300,
    "timeout_s": 45,
}

_FLAGS_DEFECTO: dict = {}


# ------------------------------------------------------------------ rangos
_RANGOS_MOTOR = {
    "w_lift": (0.0, 10.0),
    "w_counter": (0.0, 10.0),
    "w_fase": (0.0, 10.0),
    "w_precio": (0.0, 10.0),
    "w_flujo": (0.0, 10.0),
    "w_cadena": (0.0, 10.0),
    "w_tiempo": (0.0, 10.0),
    "w_venta": (0.0, 10.0),
    "lift_minimo": (-1.0, 1.0),
    "umbral_ventaja": (0.0, 1.0),
    "fase_minima_s": (0, 10000),
    "duracion_tipica_s": (1, 100000),
    "venta_minima_tasa": (0.0, 1.0),
    "venta_margen_pp": (0.0, 1000.0),
    "venta_margen_s": (0, 100000),
    "flex": (0, 10),
    "ventana_fase": (0.0, 1000.0),
}

_RANGOS_UI = {
    "ancho": (100, 100000),
    "alto": (100, 100000),
    "angosto_max": (0, 100000),
    "amplio_min": (0, 100000),
    "actualizacion_hz": (0.01, 1000.0),
}

_RANGOS_FUENTES = {
    "timeout_s": (0.01, 3600.0),
    "reintentos": (0, 100),
    "backoff_s": (0.0, 3600.0),
}

_RANGOS_AGENTE = {
    "presupuesto_llamadas_min": (0, 100000),
    "presupuesto_llamadas_sesion": (0, 1000000),
    "cache_s": (0, 1000000),
    "timeout_s": (1, 3600),
}

_STR_AGENTE = ("modelo", "proveedor", "fallback")


class Config:
    def __init__(self, motor=None, ui=None, fuentes=None, agente=None, flags=None, avisos=None):
        self.motor = motor if isinstance(motor, dict) else dict(_MOTOR_DEFECTO)
        self.ui = ui if isinstance(ui, dict) else dict(_UI_DEFECTO)
        self.fuentes = fuentes if isinstance(fuentes, dict) else dict(_FUENTES_DEFECTO)
        self.agente = agente if isinstance(agente, dict) else dict(_AGENTE_DEFECTO)
        self.flags = flags if isinstance(flags, dict) else dict(_FLAGS_DEFECTO)
        self.avisos = list(avisos) if avisos else []

    def get(self, clave, defecto=None):
        if not isinstance(clave, str) or not clave:
            return defecto
        partes = clave.split(".")
        # primera parte = sección
        if partes and partes[0] in ("motor", "ui", "fuentes", "agente", "flags"):
            cur = getattr(self, partes[0])
            partes = partes[1:]
        else:
            # buscar en todo el objeto
            cur = None
            for attr in ("motor", "ui", "fuentes", "agente", "flags"):
                if hasattr(self, attr):
                    pass
            cur = self.__dict__
        for p in partes:
            if isinstance(cur, dict):
                if p in cur:
                    cur = cur[p]
                elif p == "breakpoints" and isinstance(cur.get("breakpoints"), dict):
                    # no avanzar, se resuelve abajo
                    cur = cur  # noop
                elif isinstance(cur.get("breakpoints"), dict) and p in cur.get("breakpoints", {}):
                    cur = cur["breakpoints"][p]
                else:
                    return defecto
            elif hasattr(cur, p):
                cur = getattr(cur, p)
            else:
                return defecto
        return cur if cur is not None else defecto

    def __repr__(self):
        return f"Config(motor={self.motor!r}, ui={self.ui!r}, ...)"


def _num(v, defecto=None):
    try:
        if isinstance(v, bool):
            return defecto
        if v is None:
            return defecto
        return float(v)
    except (TypeError, ValueError):
        return defecto


def _validar_rango(seccion, clave, valor_defecto, rango, avisos, prefijo):
    lo, hi = rango
    # si la clave no existe, se deja el default ya puesto
    # (la validación solo corrige valores presentes originalmente; pero como
    #  mezclamos defaults, validamos todas las claves conocidas presentes)
    if clave not in seccion:
        seccion[clave] = valor_defecto
        return
    v = seccion[clave]
    # tipo numérico
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        avisos.append(f"{prefijo}.{clave}: valor inválido ({v!r}), se usa {valor_defecto!r}")
        seccion[clave] = valor_defecto
        return
    if v < lo or v > hi:
        avisos.append(f"{prefijo}.{clave}: valor fuera de rango ({v!r}), se usa {valor_defecto!r}")
        seccion[clave] = valor_defecto


def _validar_motor(motor, avisos):
    for k, (lo, hi) in _RANGOS_MOTOR.items():
        if k not in _MOTOR_DEFECTO:
            continue
        _validar_rango(motor, k, _MOTOR_DEFECTO[k], (lo, hi), avisos, "motor")
    # asegurar claves faltantes
    for k, v in _MOTOR_DEFECTO.items():
        if k not in motor:
            motor[k] = v
    # slots debe ser dict
    if not isinstance(motor.get("slots"), dict):
        avisos.append("motor.slots: inválido, se usa default")
        motor["slots"] = dict(_MOTOR_DEFECTO.get("slots", {}))


def _validar_ui(ui, avisos):
    # aplanar breakpoints si vienen anidados
    bp = ui.get("breakpoints")
    if isinstance(bp, dict):
        for k, v in bp.items():
            if k not in ui:
                ui[k] = v
    if "breakpoints" not in ui or not isinstance(ui.get("breakpoints"), dict):
        ui["breakpoints"] = {
            "angosto_max": ui.get("angosto_max", _UI_DEFECTO["angosto_max"]),
            "amplio_min": ui.get("amplio_min", _UI_DEFECTO["amplio_min"]),
        }
    for k, (lo, hi) in _RANGOS_UI.items():
        _validar_rango(ui, k, _UI_DEFECTO[k], (lo, hi), avisos, "ui")
    for k, v in _UI_DEFECTO.items():
        if k not in ui and k != "breakpoints":
            ui[k] = v
    # sincronizar breakpoints con valores directos
    ui["breakpoints"]["angosto_max"] = ui.get("angosto_max", _UI_DEFECTO["angosto_max"])
    ui["breakpoints"]["amplio_min"] = ui.get("amplio_min", _UI_DEFECTO["amplio_min"])


def _validar_fuentes(fuentes, avisos):
    for k, (lo, hi) in _RANGOS_FUENTES.items():
        _validar_rango(fuentes, k, _FUENTES_DEFECTO[k], (lo, hi), avisos, "fuentes")
    for k, v in _FUENTES_DEFECTO.items():
        if k not in fuentes:
            fuentes[k] = v
    # reintentos int
    if isinstance(fuentes.get("reintentos"), float):
        if fuentes["reintentos"].is_integer():
            fuentes["reintentos"] = int(fuentes["reintentos"])


def _validar_agente(agente, avisos):
    for k in _STR_AGENTE:
        v = agente.get(k, _AGENTE_DEFECTO[k])
        if not isinstance(v, str) or not v.strip():
            avisos.append(f"agente.{k}: inválido ({v!r}), se usa {_AGENTE_DEFECTO[k]!r}")
            agente[k] = _AGENTE_DEFECTO[k]
        else:
            agente[k] = v.strip() if k != "modelo" else v.strip()
    for k, (lo, hi) in _RANGOS_AGENTE.items():
        _validar_rango(agente, k, _AGENTE_DEFECTO[k], (lo, hi), avisos, "agente")
    for k, v in _AGENTE_DEFECTO.items():
        if k not in agente:
            agente[k] = v


def _validar_flags(flags, avisos):
    if not isinstance(flags, dict):
        avisos.append("flags: sección inválida; se usan defaults")
        return dict(_FLAGS_DEFECTO)
    out = {}
    for k, v in flags.items():
        if not isinstance(v, bool):
            avisos.append(f"flags.{k}: no booleano ({v!r}), se usa False")
            out[k] = False
        else:
            out[k] = v
    return out


def cargar(ruta=None):
    if ruta is None:
        ruta = _RUTA_DEFAULT

    avisos = []
    datos = {}

    if not os.path.exists(ruta):
        avisos.append(f"archivo no encontrado: {ruta}; se usan defaults")
    else:
        try:
            with open(ruta, encoding="utf-8") as f:
                raw = f.read()
        except Exception as e:
            avisos.append(f"no se pudo leer {ruta}: {e}; se usan defaults")
            raw = ""

        parsed = None
        # intentar YAML
        try:
            import yaml

            parsed = yaml.safe_load(raw)
        except Exception:
            # PyYAML no disponible o falló: intentar JSON
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = None
                avisos.append("YAML roto o ilegible: se usan defaults")

        # si YAML se importó pero devolvió algo no-dict, intentar JSON
        if parsed is not None and not isinstance(parsed, dict):
            try:
                parsed2 = json.loads(raw)
                if isinstance(parsed2, dict):
                    parsed = parsed2
            except Exception:
                pass

        if parsed is None:
            if raw.strip() != "":
                # solo anotar si no se anotó ya
                if not any("YAML roto" in a for a in avisos):
                    avisos.append("YAML roto o ilegible: se usan defaults")
            parsed = {}
        if not isinstance(parsed, dict):
            avisos.append("la raíz del YAML no es un dict: se usan defaults")
            parsed = {}
        datos = parsed

    # secciones
    def _seccion(nombre, defecto):
        raw_sec = datos.get(nombre, None) if isinstance(datos, dict) else None
        if raw_sec is None:
            return dict(defecto), None
        if not isinstance(raw_sec, dict):
            avisos.append(f"sección {nombre}: inválida; se usan defaults")
            return dict(defecto), "invalida"
        out = dict(defecto)
        out.update(raw_sec)
        return out, None

    motor, _ = _seccion("motor", _MOTOR_DEFECTO)
    ui, _ = _seccion("ui", _UI_DEFECTO)
    fuentes, _ = _seccion("fuentes", _FUENTES_DEFECTO)
    agente, _ = _seccion("agente", _AGENTE_DEFECTO)
    flags_raw = datos.get("flags", {}) if isinstance(datos, dict) else {}
    if flags_raw is None:
        flags_raw = {}
    if isinstance(flags_raw, dict):
        flags = dict(flags_raw)
    else:
        avisos.append("sección flags: inválida; se usan defaults")
        flags = dict(_FLAGS_DEFECTO)

    _validar_motor(motor, avisos)
    _validar_ui(ui, avisos)
    _validar_fuentes(fuentes, avisos)
    _validar_agente(agente, avisos)
    flags = _validar_flags(flags, avisos)

    return Config(motor=motor, ui=ui, fuentes=fuentes, agente=agente, flags=flags, avisos=avisos)


def guardar(cfg, ruta):
    if ruta is None:
        ruta = _RUTA_DEFAULT
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    datos = {
        "motor": getattr(cfg, "motor", {}),
        "ui": getattr(cfg, "ui", {}),
        "fuentes": getattr(cfg, "fuentes", {}),
        "agente": getattr(cfg, "agente", {}),
        "flags": getattr(cfg, "flags", {}),
    }
    try:
        import yaml

        with open(ruta, "w", encoding="utf-8") as f:
            yaml.safe_dump(datos, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    except Exception:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)

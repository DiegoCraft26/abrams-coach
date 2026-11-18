#!/usr/bin/env python3
"""¿Está todo listo para jugar? Un chequeo antes de encolar, no después de perder.

Revisa las siete cosas que, si fallan, te dejan sin coach a mitad de partida y sin saber
por qué:

    1. cuenta de Steam en `.cuenta`
    2. red con deadlock-api
    3. captura por KWin (o spectacle de respaldo)
    4. overlay (libgtk4-layer-shell + Gtk4LayerShell)
    5. puerto 8090 libre o coach ya corriendo
    6. disco con espacio para logs y notas
    7. modo silencio apagado (si no, no aparece ninguna ventana)
    + objetivo de la sesión activo, si lo hay

No arregla nada: dice qué falta y el comando exacto para arreglarlo. Lo que no se puede
comprobar sin jugar (que el overlay se vea encima del juego) no se finge que se comprueba.

Uso:
    abrams-coach listo
    python3 herramientas/listo.py --json

Código: 0 todo listo · 1 algo falta.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LIBS_OVERLAY = ("/usr/lib/libgtk4-layer-shell.so", "/usr/lib64/libgtk4-layer-shell.so")
API = "https://api.deadlock-api.com"


def _run(cmd, timeout=5):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def cuenta() -> tuple[bool, str, str]:
    ruta = RAIZ / ".cuenta"
    try:
        valor = ruta.read_text(encoding="utf-8").strip()
    except OSError:
        return False, "sin .cuenta", "echo 123456789 > .cuenta   (tu account_id de Deadlock)"
    if not valor.isdigit():
        return False, f".cuenta no es un número: {valor[:12]!r}", "escribe solo el account_id"
    return True, f"account_id {valor}", ""


def red() -> tuple[bool, str, str]:
    req = urllib.request.Request(f"{API}/v1/patches", headers={"User-Agent": "abrams-coach/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:      # noqa: S310
            return (r.status == 200, f"deadlock-api {r.status}", "")
    except Exception as exc:                                    # noqa: BLE001
        return False, f"sin respuesta ({type(exc).__name__})", "revisa la conexión; el coach sigue con lo local"


def captura() -> tuple[bool, str, str]:
    codigo, salida = _run(["busctl", "--user", "list", "--no-legend"])
    if codigo == 0 and "org.kde.KWin" in salida:
        return True, "KWin por D-Bus", ""
    if shutil.which("spectacle"):
        return True, "spectacle (respaldo)", ""
    return False, "ni KWin ni spectacle", "sudo pacman -S spectacle   (o usa KDE)"


def overlay() -> tuple[bool, str, str]:
    lib = next((x for x in LIBS_OVERLAY if os.path.exists(x)), None)
    if not lib:
        return False, "falta libgtk4-layer-shell", "sudo pacman -S gtk4-layer-shell"
    try:
        import gi
        gi.require_version("Gtk4LayerShell", "1.0")             # noqa: F401
    except Exception:                                           # noqa: BLE001
        return False, f"{Path(lib).name} sin typelib de Gtk4LayerShell", "reinstala gtk4-layer-shell"
    return True, Path(lib).name, ""


def puerto() -> tuple[bool, str, str]:
    with socket.socket() as s:
        # El servidor del coach usa allow_reuse_address: sin SO_REUSEADDR, un socket en
        # TIME_WAIT daría un «falta» falso.
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", 8090))
            return True, "8090 libre", ""
        except OSError:
            pass
    try:
        with urllib.request.urlopen("http://127.0.0.1:8090/api/salud", timeout=2) as r:  # noqa: S310
            r.read(1)
        return True, "8090 ocupado por el coach", ""
    except Exception:                                           # noqa: BLE001
        return False, "8090 ocupado por otra cosa", "abrams-coach parar"


def disco() -> tuple[bool, str, str]:
    libre = shutil.disk_usage(str(RAIZ)).free
    gb = libre / (1 << 30)
    return (gb > 2, f"{gb:.1f} GB libres", "" if gb > 2 else "libera espacio: los logs y notas pesan poco, pero el archivo de partidas no")


def silencio() -> tuple[bool, str, str]:
    ruta = Path.home() / ".abrams-silencio"
    if ruta.exists():
        return False, "modo silencio activo: no aparecerá ninguna ventana", f"rm {ruta}"
    return True, "ventanas permitidas", ""


def objetivo() -> tuple[bool | None, str, str]:
    ruta = RAIZ / "salida" / "plan_actual.json"
    try:
        doc = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "sin objetivo de sesión (corre `abrams-coach plan`)", ""
    regla = doc.get("regla")
    if regla not in ("muertes", "participacion"):
        return None, "objetivo viejo con una regla retirada", "abrams-coach plan --nuevo"
    etiqueta = {"muertes": f"≤{doc.get('meta')} muertes",
                "participacion": f"≥{doc.get('meta')} k+a/min"}[regla]
    return True, f"objetivo: {doc.get('necesarias')} de {doc.get('partidas')} con {etiqueta}", ""


def clave_api():
    """¿Hay X-API-KEY? No es obligatoria, pero sin ella la cuota por IP manda."""
    valor = (os.environ.get("DEADLOCK_API_KEY") or "").strip()
    if not valor:
        try:
            valor = Path(os.path.expanduser("~/.config/abrams-coach/api_key")).read_text(
                encoding="utf-8").strip().splitlines()[0].strip()
        except (OSError, IndexError):
            valor = ""
    if valor:
        return True, f"configurada ({valor[:4]}…)", ""
    return None, "sin clave: la cuota de la API es por IP (hoy rota)",         "pide una en el Discord de deadlock-api y guárdala en ~/.config/abrams-coach/api_key"


CHECKS = (("cuenta", cuenta), ("red", red), ("clave API", clave_api), ("captura", captura),
          ("overlay", overlay), ("puerto", puerto), ("disco", disco), ("silencio", silencio))


def evaluar() -> dict:
    filas = []
    for nombre, fn in CHECKS:
        try:
            ok, detalle, arreglo = fn()
        except Exception as exc:                                # noqa: BLE001
            ok, detalle, arreglo = False, f"error: {exc}", ""
        filas.append({"nombre": nombre, "ok": ok, "detalle": detalle, "arreglo": arreglo})
    ok_obj, det_obj, arr_obj = objetivo()
    filas.append({"nombre": "objetivo", "ok": ok_obj, "detalle": det_obj, "arreglo": arr_obj})
    faltan = [f for f in filas if f["ok"] is False]
    return {"filas": filas, "faltan": [f["nombre"] for f in faltan],
            "listo": not faltan}


def texto(r: dict) -> str:
    lineas = []
    for f in r["filas"]:
        marca = "ok   " if f["ok"] is True else ("falta" if f["ok"] is False else "—    ")
        lineas.append(f"  {marca} {f['nombre']:9s} {f['detalle']}")
        if f["ok"] is False and f["arreglo"]:
            lineas.append(f"           → {f['arreglo']}")
    lineas.append("")
    lineas.append("todo listo para jugar" if r["listo"]
                  else f"falta: {', '.join(r['faltan'])}")
    lineas.append("(que el overlay se vea encima del juego no se puede comprobar sin abrirlo)")
    return "\n".join(lineas)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Chequeo antes de jugar")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = evaluar()
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(texto(r))
    return 0 if r["listo"] else 1


if __name__ == "__main__":
    sys.exit(main())

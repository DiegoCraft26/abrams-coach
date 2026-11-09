#!/usr/bin/env python3
"""Coloca la ventana del panel en el monitor que se le diga.

Por qué existe: en Wayland una aplicación no puede colocarse sola (KWin decide dónde
nace la ventana), así que `gtk_window_move` no hace nada y el panel salía siempre en el
monitor principal. La forma correcta es pedírselo al compositor: se carga un script de
KWin por DBus, se mueve la ventana a las coordenadas del monitor pedido y se descarga
el script para no dejar nada corriendo.

Uso:
    python3 herramientas/colocar_panel.py                 # monitor secundario
    python3 herramientas/colocar_panel.py HDMI-A-1        # por nombre de salida
    python3 herramientas/colocar_panel.py --listar        # ver salidas disponibles
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import time

ANSI = re.compile(r"\x1b\[[0-9;]*m")

BUS = "org.kde.KWin"
RUTA = "/Scripting"
IFACE = "org.kde.kwin.Scripting"
NOMBRE_SCRIPT = "abrams-colocar-panel"
CLASE = "gg.diego.abramscoach"   # app_id real del panel; el título lo comparten otras ventanas

GUION = """
(function () {
    var destino = "%(salida)s";
    var pantallas = workspace.screens || [];
    var elegida = null;
    for (var i = 0; i < pantallas.length; i++) {
        if (pantallas[i].name === destino) { elegida = pantallas[i]; }
    }
    if (!elegida) {
        print("abrams: no existe la salida " + destino);
        return;
    }
    var g = elegida.geometry;
    // Por defecto, la mitad derecha del monitor y a toda la altura: así no se monta
    // sobre la ventana que ya esté abierta a la izquierda.
    var ancho = Math.min(%(ancho)d, Math.floor(g.width / 2) - 6);
    var alto = Math.min(%(alto)d, g.height - 20);
    var x = g.x + Math.floor(g.width / 2) + 3;
    var y = g.y + 10;
    var lista = workspace.windowList();
    for (var j = 0; j < lista.length; j++) {
        var w = lista[j];
        if ((w.resourceClass || "") === "%(clase)s") {
            // Sin foco ni protagonismo: el panel se mira, no se usa. Con el juego en
            // pantalla completa, una ventana que sube te saca de la partida.
            w.keepBelow = true;
            w.skipTaskbar = true;
            w.skipPager = true;
            w.frameGeometry = { x: x, y: y, width: ancho, height: alto };
            print("abrams: panel en " + destino + " (" + x + "," + y + ") " + ancho + "x" + alto);
        }
    }
})();
"""


def _dbus(metodo, *args):
    cmd = ["gdbus", "call", "--session", "--dest", BUS, "--object-path", RUTA,
           "--method", f"{IFACE}.{metodo}", *args]
    salida = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if salida.returncode != 0:
        raise RuntimeError((salida.stderr or salida.stdout).strip())
    return salida.stdout.strip()


def salidas():
    """[(nombre, x, y, ancho, alto, prioridad)] de los monitores, vía kscreen-doctor.

    La prioridad la pone KDE: 1 es el monitor principal. Sirve para saber cuál es el
    secundario sin adivinar por el orden de la lista (que es el orden de conexión).
    """
    try:
        texto = subprocess.run(["kscreen-doctor", "-o"], capture_output=True,
                               text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    monitores, actual = [], None
    for linea in ANSI.sub("", texto).splitlines():
        limpia = linea.strip()
        if limpia.startswith("Output:"):
            partes = limpia.split()
            nombre = partes[2] if len(partes) > 2 else None
            actual = {"nombre": nombre, "prioridad": 99}
        elif actual and limpia.startswith("priority"):
            try:
                actual["prioridad"] = int(limpia.split()[1])
            except (IndexError, ValueError):
                pass
        elif actual and limpia.startswith("Geometry:"):
            geo = limpia.split("Geometry:")[1].split()
            try:
                x, y = (int(v) for v in geo[0].split(","))
                ancho, alto = (int(v) for v in geo[1].split("x"))
            except (IndexError, ValueError):
                actual = None
                continue
            actual.update({"x": x, "y": y, "ancho": ancho, "alto": alto})
            monitores.append(actual)
            actual = None
    return monitores


def colocar(salida=None, ancho=900, alto=1020, espera=0.0):
    """Mueve la ventana del panel a `salida`. Devuelve el nombre de la salida usada."""
    monitores = salidas()
    if not monitores:
        raise RuntimeError("no pude leer los monitores (¿kscreen-doctor?)")
    if espera:
        time.sleep(espera)
    nombres = [m["nombre"] for m in monitores]
    if salida is None:
        # Secundario = el de prioridad más alta (KDE pone 1 al principal).
        secundarios = sorted(monitores, key=lambda m: -m["prioridad"])
        salida = secundarios[0]["nombre"] if secundarios else nombres[0]
    if salida not in nombres:
        raise RuntimeError(f"salida {salida} no existe; hay {nombres}")

    fd, ruta = tempfile.mkstemp(prefix="abrams-kwin-", suffix=".js")
    os.close(fd)
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(GUION % {"salida": salida, "ancho": ancho, "alto": alto,
                             "clase": CLASE})
        _dbus("unloadScript", NOMBRE_SCRIPT)
        _dbus("loadScript", ruta, NOMBRE_SCRIPT)
        _dbus("start")
    finally:
        try:
            os.unlink(ruta)
        except OSError:
            pass
    time.sleep(0.3)
    _dbus("unloadScript", NOMBRE_SCRIPT)
    return salida


def main():
    ap = argparse.ArgumentParser(description="Coloca el panel en otro monitor")
    ap.add_argument("salida", nargs="?", default=None,
                    help="nombre de la salida (por defecto, el secundario)")
    ap.add_argument("--ancho", type=int, default=980)
    ap.add_argument("--alto", type=int, default=1080)
    ap.add_argument("--listar", action="store_true", help="solo enseña los monitores")
    a = ap.parse_args()
    if a.listar:
        for m in salidas():
            print(f"{m['nombre']}: {m['ancho']}x{m['alto']} en {m['x']},{m['y']}"
                  f" · prioridad {m['prioridad']}")
        return 0
    try:
        usada = colocar(a.salida, a.ancho, a.alto)
    except Exception as exc:                                   # noqa: BLE001
        print(f"no pude colocar el panel: {exc}")
        return 1
    print(f"panel colocado en {usada}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

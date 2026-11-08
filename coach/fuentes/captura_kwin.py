"""Captura de pantalla por región con KWin ScreenShot2 (DBus).

Por qué existe: en Wayland/KDE la vía de `spectacle -f` cuesta ~415 ms y deja un PNG de
450 KB en disco. KWin ya sabe entregar los píxeles crudos de una caja por DBus y eso
cuesta milisegundos. La receta completa está en `docs/experto/vision.md`.

Medido el 2026-11-08 en esta máquina (KWin 6.8.2, escritorio 4480x1440, sin partida),
mediana de 8 capturas:
    reloj 115x44 .......... 0.9 ms        banda de oro 500x360 ... 2.5 ms
    MATCH 430x110 ......... 1.2 ms        escritorio entero ..... 34 ms
    `spectacle -f` ...... 415 ms          (el método viejo, con PNG de 450 KB en disco)

Trampas que ya pagamos:
  - el descriptor va por el extremo de ESCRITURA del pipe: con el de lectura llegan los
    metadatos correctos y cero bytes;
  - KWin no cierra su extremo, así que no hay EOF: se leen `stride*alto` bytes y se corta;
  - el pipe son 64 KB y el compositor escribe en síncrono: hay que drenarlo en otro hilo
    o la llamada no vuelve nunca.

Una sola captura a la vez en todo el proceso (`_LOCK`): el resto de los lectores espera
milisegundos, nunca hay dos capturas en paralelo.
"""
import os
import select
import threading
import time

BUS = "org.kde.KWin"
RUTA = "/org/kde/KWin/ScreenShot2"
IFACE = "org.kde.KWin.ScreenShot2"

#: Si KWin no contesta en este tiempo, `capturar()` devuelve None y el llamador se va al
#: método viejo. No se bloquea más que esto.
TIMEOUT_MS = 300

_LOCK = threading.Lock()             # una captura a la vez
_LOCK_ESTADO = threading.Lock()
_ESTADO = {"probado": False, "sirve": False, "error": None, "version": None,
           "Gio": None, "GLib": None, "Image": None, "con": None}


def disponible():
    """True si esta sesión tiene KWin con ScreenShot2. Se decide una vez por proceso."""
    with _LOCK_ESTADO:
        if not _ESTADO["probado"]:
            _ESTADO["probado"] = True
            _ESTADO["sirve"] = _arrancar()
        return _ESTADO["sirve"]


def _arrancar():
    """Importa gi y pregunta la versión de la interfaz. Deja la conexión lista."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        from PIL import Image
    except Exception as exc:                                    # noqa: BLE001
        _ESTADO["error"] = f"sin gi/PIL: {type(exc).__name__}: {exc}"
        return False
    try:
        con = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        leido = con.call_sync(
            BUS, RUTA, "org.freedesktop.DBus.Properties", "Get",
            GLib.Variant.new_tuple(GLib.Variant("s", IFACE),
                                   GLib.Variant("s", "Version")),
            GLib.VariantType.new("(v)"), Gio.DBusCallFlags.NONE, TIMEOUT_MS, None)
        _ESTADO.update({"Gio": Gio, "GLib": GLib, "Image": Image, "con": con,
                        "version": leido.unpack()[0]})
        return True
    except Exception as exc:                                    # noqa: BLE001
        _ESTADO["error"] = f"KWin sin ScreenShot2: {type(exc).__name__}: {exc}"
        return False


def capturar(x, y, ancho, alto, timeout_ms=TIMEOUT_MS):
    """Imagen PIL en modo RGB de esa caja del escritorio, o None si no se pudo."""
    return _pedir("CaptureArea", (int(x), int(y), int(ancho), int(alto)), timeout_ms)


def capturar_escritorio(timeout_ms=TIMEOUT_MS):
    """Imagen PIL del escritorio completo, o None si no se pudo."""
    return _pedir("CaptureWorkspace", None, timeout_ms)


def _pedir(metodo, caja, timeout_ms):
    if not disponible() or _ESTADO["con"] is None:
        return None
    Gio, GLib, Image = _ESTADO["Gio"], _ESTADO["GLib"], _ESTADO["Image"]
    with _LOCK:
        trozos = []
        rd, wr = os.pipe()
        fds = Gio.UnixFDList.new()
        h = fds.append(wr)                    # extremo de ESCRITURA, no el de lectura

        def drenar():
            """Vacía el pipe mientras KWin escribe; sin esto la llamada se queda colgada."""
            try:
                while select.select([rd], [], [], 0.02)[0]:
                    b = os.read(rd, 1 << 20)
                    if not b:
                        break
                    trozos.append(b)
            except OSError:
                pass
            finally:
                os.close(rd)

        threading.Thread(target=drenar, daemon=True).start()
        opciones = GLib.Variant("a{sv}", {"include-cursor": GLib.Variant("b", False)})
        if caja:
            args = GLib.Variant.new_tuple(
                GLib.Variant("i", caja[0]), GLib.Variant("i", caja[1]),
                GLib.Variant("u", caja[2]), GLib.Variant("u", caja[3]),
                opciones, GLib.Variant("h", h))
        else:
            args = GLib.Variant.new_tuple(opciones, GLib.Variant("h", h))
        try:
            res = _ESTADO["con"].call_with_unix_fd_list_sync(
                BUS, RUTA, IFACE, metodo, args, GLib.VariantType.new("(a{sv})"),
                Gio.DBusCallFlags.NONE, timeout_ms, fds, None)
            meta = res[0].unpack()[0]
        except Exception as exc:                                # noqa: BLE001
            _ESTADO["error"] = f"{metodo}: {type(exc).__name__}: {exc}"
            return None
        finally:
            os.close(wr)                      # KWin no cierra el suyo: no hay EOF

        esperado = int(meta.get("stride") or 0) * int(meta.get("height") or 0)
        limite = time.perf_counter() + 2.0
        while sum(map(len, trozos)) < esperado and time.perf_counter() < limite:
            time.sleep(0.0005)
        datos = b"".join(trozos)
        if meta.get("format") != 16 or len(datos) < esperado:
            _ESTADO["error"] = (f"{metodo}: format={meta.get('format')} "
                                f"y {len(datos)}/{esperado} bytes")
            return None
        _ESTADO["error"] = None
        return Image.frombuffer("RGB", (meta["width"], meta["height"]), datos,
                                "raw", "RGBX", meta["stride"], 1)

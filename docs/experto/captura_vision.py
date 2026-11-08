import os, select, threading, time, sys
import gi; gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib
from PIL import Image
BUS, RUTA, IFACE = "org.kde.KWin", "/org/kde/KWin/ScreenShot2", "org.kde.KWin.ScreenShot2"

def capturar(x, y, ancho, alto):
    trozos, parar = [], threading.Event()
    r, w = os.pipe()
    fds = Gio.UnixFDList.new(); h = fds.append(w)        # extremo de ESCRITURA
    def drenar():                                        # 64 KB de pipe: hay que vaciarlo
        try:
            while not parar.is_set() and select.select([r], [], [], 0.02)[0]:
                b = os.read(r, 1 << 20)
                if not b: return
                trozos.append(b)
        except OSError: pass
        finally: os.close(r)
    threading.Thread(target=drenar, daemon=True).start()
    pet = GLib.Variant.new_tuple(GLib.Variant("i", x), GLib.Variant("i", y),
        GLib.Variant("u", ancho), GLib.Variant("u", alto),
        GLib.Variant("a{sv}", {"include-cursor": GLib.Variant("b", False)}),
        GLib.Variant("h", h))
    con = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    try:
        res = con.call_with_unix_fd_list_sync(BUS, RUTA, IFACE, "CaptureArea", pet,
            GLib.VariantType.new("(a{sv})"), Gio.DBusCallFlags.NONE, 5000, fds, None)
        meta = res[0].unpack()[0]
    finally: os.close(w)                                 # KWin no cierra el suyo: no hay EOF
    esperado = meta["stride"] * meta["height"]; limite = time.perf_counter() + 2
    while sum(map(len, trozos)) < esperado and time.perf_counter() < limite: time.sleep(0.0005)
    parar.set(); datos = b"".join(trozos)
    assert meta["format"] == 16 and len(datos) >= esperado, (meta, len(datos))
    return Image.frombuffer("RGB", (meta["width"], meta["height"]), datos, "raw", "RGBX",
                            meta["stride"], 1)

if __name__ == "__main__":
    t0 = time.perf_counter(); im = capturar(*map(int, sys.argv[1:5]))
    im.convert("RGB").save("/tmp/vision-ultimo.png")
    print(f"{im.size[0]}x{im.size[1]} {(time.perf_counter()-t0)*1000:.2f} ms")

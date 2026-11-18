#!/usr/bin/env python3
"""Modo espera: arranca el coach cuando abres Deadlock y lo cierra cuando sales.

Es lo que hace que la app se sienta parte del juego sin tocar el juego: solo mira la lista
de procesos cada pocos segundos.

Uso:
    python3 herramientas/vigilar.py            # espera, arranca, cierra y archiva
    python3 herramientas/vigilar.py --sin-panel

Al terminar la partida: cierra el coach, archiva en SQLite y escribe el informe.
"""
import argparse
import fcntl
import os
import signal
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

LOG = "/tmp/abrams-vigilar.log"
PANEL_LOG = "/tmp/abrams-panel.log"
OVERLAY_LOG = "/tmp/abrams-overlay.log"
PUERTO = 8090
# Un solo vigilante por máquina. El 2026-11-09 quedó uno viejo corriendo 4 h junto al
# servicio de systemd y cada uno reabría el panel por su cuenta: la ventana aparecía
# encima del juego sin que nadie la pidiera.
BLOQUEO = "/tmp/abrams-vigilar.lock"
# Si este archivo existe, el vigilante espera pero NO abre el panel. Es el interruptor
# de Diego: `touch ~/.abrams-silencio` para que no aparezca nada.
SILENCIO = os.path.join(os.path.expanduser("~"), ".abrams-silencio")
# Si el panel se cae solo, no se reabre más de una vez cada 5 min (evita el bucle).
MIN_ENTRE_REAPERTURAS_S = 300.0
# Un panel que vive menos que esto no arrancó: lo normal es que GDK no vea pantalla.
PANEL_ROTO_S = 10.0
# Tras tres intentos así, se deja de reabrir hasta la siguiente partida.
MAX_PANEL_ROTOS = 3


def registrar(texto):
    linea = f"{time.strftime('%H:%M:%S')} {texto}"
    print(linea, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass


def describir_fin(codigo):
    """Cómo terminó un proceso: código, señal o «sigue vivo».

    Distinguir «matado por SIGKILL» (casi siempre falta de memoria) de «código 1» (error
    propio) es lo que faltaba para entender por qué el panel desaparecía sin traza.
    """
    if codigo is None:
        return "sigue vivo"
    if codigo < 0:
        try:
            nombre = signal.Signals(-codigo).name
        except ValueError:
            nombre = f"señal {-codigo}"
        aviso = " (falta de memoria o cierre forzado)" if -codigo == signal.SIGKILL else ""
        return f"matado por {nombre}{aviso}"
    return f"código {codigo}"


def revisar_hijos(procesos, inicios=None):
    """Anota los hijos que ya terminaron.

    Devuelve `(vivos, muertes)`. Cada muerte lleva cuántos segundos vivió el proceso:
    un panel que muere a los 0–10 s no es "se cerró", es "no arrancó" (GTK sin
    pantalla, por ejemplo), y reabrirlo cada 5 min solo molesta.
    """
    vivos, muertes = [], []
    for p in procesos:
        codigo = p.poll()
        if codigo is None:
            vivos.append(p)
        else:
            nombre = os.path.basename(p.args[1] if len(p.args) > 1 else p.args[0])
            registrar(f"{nombre} (pid {p.pid}) terminó: {describir_fin(codigo)}")
            inicio = (inicios or {}).get(p.pid)
            muertes.append((nombre, p.pid, codigo,
                            time.time() - inicio if inicio else None))
    return vivos, muertes


def puerto_libre(puerto=PUERTO):
    import socket
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", puerto)) != 0


def cuenta_guardada():
    """SteamID64 de .cuenta, si existe. Sin cuenta el modo vivo usa el HUD."""
    try:
        with open(os.path.join(RAIZ, ".cuenta"), encoding="utf-8") as f:
            valor = f.read().strip()
        return valor if valor.isdigit() else None
    except OSError:
        return None


def _es_panel(pid):
    """True si ese pid es un panel de verdad y está vivo.

    Un zombi contesta `os.kill(pid, 0)` como si estuviera vivo porque el padre no lo ha
    recogido. Con eso, el vigilante se creía acompañado para siempre y no volvía a abrir
    el panel: el panel se moría y nadie lo notaba. Se mira el estado en /proc y que la
    línea de órdenes sea la del panel.
    """
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as f:
            estado = f.read().rsplit(")", 1)[-1].split()[0]
        if estado == "Z":
            return False
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return b"panel_nativo.py" in f.read()
    except (OSError, IndexError):
        return False


def tomar_bloqueo(ruta=BLOQUEO):
    """Bloqueo exclusivo del vigilante. None si ya hay otro corriendo.

    Se devuelve el archivo abierto (hay que mantenerlo vivo) o None. Sin esto, dos
    vigilantes conviven y el panel se abre dos veces.
    """
    try:
        archivo = open(ruta, "w", encoding="utf-8")
    except OSError:
        return None
    try:
        fcntl.flock(archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        archivo.close()
        return None
    archivo.write(str(os.getpid()))
    archivo.flush()
    return archivo


def en_silencio(ruta=SILENCIO):
    """True si Diego pidió que no aparezca ninguna ventana."""
    return os.path.exists(ruta)


def panel_vivo():
    """PID del panel si sigue vivo. Sirve para no abrir dos y para reabrirlo si muere."""
    try:
        with open("/tmp/abrams-panel.pid", encoding="utf-8") as f:
            pid = int(f.read().strip())
        if _es_panel(pid):
            return pid
    except (OSError, ValueError):
        pass
    # El PID puede estar viejo si el panel se abrió a mano: se busca por proceso antes
    # de lanzar otro. Así no se acumulan ventanas.
    try:
        salida = subprocess.run(["pgrep", "-f", "[p]anel_nativo.py"],
                                capture_output=True, text=True, timeout=5).stdout
        for linea in salida.split():
            pid = int(linea)
            # `pgrep` también lista zombis y atérmicos: se confirma con /proc antes de
            # dar el panel por vivo.
            if not _es_panel(pid):
                continue
            with open("/tmp/abrams-panel.pid", "w", encoding="utf-8") as f:
                f.write(str(pid))
            return pid
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def _es_overlay(pid):
    """True si ese pid es el overlay y sigue vivo (misma trampa de zombis que el panel)."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as f:
            estado = f.read().rsplit(")", 1)[-1].split()[0]
        if estado == "Z":
            return False
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return b"overlay.py" in f.read()
    except (OSError, IndexError):
        return False


def overlay_vivo():
    """PID del overlay si sigue vivo. Uno solo: dos tarjetas encima del HUD es un error."""
    try:
        with open("/tmp/abrams-overlay.pid", encoding="utf-8") as f:
            pid = int(f.read().strip())
        if _es_overlay(pid):
            return pid
    except (OSError, ValueError):
        pass
    try:
        salida = subprocess.run(["pgrep", "-f", "[o]verlay.py"],
                                capture_output=True, text=True, timeout=5).stdout
        for linea in salida.split():
            pid = int(linea)
            if not _es_overlay(pid):
                continue
            with open("/tmp/abrams-overlay.pid", "w", encoding="utf-8") as f:
                f.write(str(pid))
            return pid
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def abrir_overlay(procesos, inicios=None):
    """Abre la tarjeta encima del HUD. Vive mientras viva la partida."""
    try:
        salida = open(OVERLAY_LOG, "a", encoding="utf-8")
    except OSError:
        salida = subprocess.DEVNULL
    procesos.append(subprocess.Popen(
        [sys.executable, os.path.join(RAIZ, "herramientas", "overlay.py"),
         "--url", f"http://127.0.0.1:{PUERTO}"],
        cwd=RAIZ, stdout=salida, stderr=subprocess.STDOUT))
    with open("/tmp/abrams-overlay.pid", "w", encoding="utf-8") as f:
        f.write(str(procesos[-1].pid))
    if inicios is not None:
        inicios[procesos[-1].pid] = time.time()


def abrir_panel(a, procesos, inicios=None):
    # La salida del panel NO va a /dev/null: era la razón de que su muerte no dejara
    # rastro. El mismo archivo que revisa Diego en /tmp/abrams-panel.log.
    try:
        salida = open(PANEL_LOG, "a", encoding="utf-8")
    except OSError:
        salida = subprocess.DEVNULL
    procesos.append(subprocess.Popen(
        [sys.executable, os.path.join(RAIZ, "panel_nativo.py"),
         "--url", f"http://127.0.0.1:{PUERTO}"],
        cwd=RAIZ, stdout=salida, stderr=subprocess.STDOUT))
    with open("/tmp/abrams-panel.pid", "w", encoding="utf-8") as f:
        f.write(str(procesos[-1].pid))
    if inicios is not None:
        inicios[procesos[-1].pid] = time.time()
    time.sleep(2)
    subprocess.run(
        [sys.executable, os.path.join(RAIZ, "herramientas", "colocar_panel.py")],
        cwd=RAIZ, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, timeout=20)


def lanzar_nota():
    """Nota de la última partida en segundo plano.

    Se lanza aparte a propósito: la consulta de la demo tarda 30 s o más y el vigilante
    no puede quedarse esperando con el juego cerrado. La nota queda en
    `salida/ultima_nota.txt` y, si hay `notify-send`, sale como aviso del escritorio.
    """
    script = (
        f"cd {RAIZ!r} && {sys.executable!r} herramientas/demos/nota.py --ultima "
        "--rondas-demo 3 --espera-demo 300 --guardar --salida salida/ultima_nota.txt "
        ">/tmp/abrams-nota.log 2>&1; "
        "if command -v notify-send >/dev/null 2>&1 && [ -s salida/ultima_nota.txt ]; then "
        "notify-send -a 'Abrams Coach' -i input-gaming \"$(head -4 salida/ultima_nota.txt)\" "
        "|| true; fi"
    )
    try:
        subprocess.Popen(["bash", "-c", script], cwd=RAIZ, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


def juego_abierto():
    """True si Deadlock corre. Se mira la lista de argumentos porque `comm` es wine."""
    try:
        salida = subprocess.run(["ps", "-eo", "args"], capture_output=True,
                                text=True, timeout=5).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False
    return any(n in salida for n in ("deadlock.exe", "deadlock/game/bin", "project8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-panel", action="store_true")
    ap.add_argument("--sin-overlay", action="store_true",
                    help="no abre la tarjeta encima del HUD")
    ap.add_argument("--intervalo", type=float, default=5.0)
    a = ap.parse_args()

    bloqueo = tomar_bloqueo()
    if bloqueo is None:
        registrar("ya hay otro vigilante corriendo; este se va")
        return 0
    if en_silencio():
        registrar(f"modo silencio ({SILENCIO}): no se abrirá el panel")

    registrar("modo espera: abre Deadlock cuando quieras")
    procesos = []
    inicios = {}
    dentro = False
    ultima_apertura = [0.0]
    fallos_panel = [0]
    reabrir = [True]
    while True:
        procesos, muertes = revisar_hijos(procesos, inicios)
        for nombre, pid, codigo, vivio_s in muertes:
            if "panel_nativo" not in (nombre or "") or vivio_s is None:
                continue
            if vivio_s < PANEL_ROTO_S:
                fallos_panel[0] += 1
                if fallos_panel[0] >= MAX_PANEL_ROTOS:
                    reabrir[0] = False
                    registrar(f"el panel murió {fallos_panel[0]} veces al arrancar "
                              f"(la última a los {vivio_s:.1f} s): no lo reabro más. "
                              "Mira /tmp/abrams-panel-crash.log; "
                              "`touch ~/.abrams-silencio` lo apaga del todo")
            else:
                fallos_panel[0] = 0
        abierto = juego_abierto()
        if abierto and not dentro:
            dentro = True
            registrar("Deadlock abierto: arrancando el coach")
            try:
                if puerto_libre():
                    orden = [sys.executable, os.path.join(RAIZ, "run.py"),
                             "--fuente", "auto", "--puerto", str(PUERTO)]
                    cuenta = cuenta_guardada()
                    if cuenta:
                        orden += ["--cuenta", cuenta]
                    # Sin esto el marcador se leía pero el coach no sabía cuál de las
                    # 12 almas eras tú y el panel decía «no sé cuál eres tú» toda la
                    # partida. Se puede cambiar con ABRAMS_HEROE=otro.
                    heroe = os.environ.get("ABRAMS_HEROE", "abrams").strip()
                    if heroe:
                        orden += ["--mi-heroe", heroe]
                    procesos.append(subprocess.Popen(
                        orden, cwd=RAIZ, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL))
                else:
                    registrar("el coach ya estaba corriendo en :8090")
                if (not a.sin_panel and not en_silencio() and reabrir[0]
                        and panel_vivo() is None):
                    abrir_panel(a, procesos, inicios)
                    ultima_apertura[0] = time.time()
                if (not a.sin_overlay and not en_silencio()
                        and overlay_vivo() is None):
                    abrir_overlay(procesos, inicios)
            except (OSError, subprocess.SubprocessError) as exc:
                registrar(f"no pude arrancar: {exc}")
        elif abierto and dentro and not a.sin_panel:
            # El panel es de solo mirar: si se cierra o se cae, se reabre solo. Pero si
            # muere al arrancar una y otra vez no es "se cayó": está roto, y reabrirlo
            # cada 5 min es justo lo que molesta.
            if (panel_vivo() is None and not en_silencio() and reabrir[0]
                    and time.time() - ultima_apertura[0] > MIN_ENTRE_REAPERTURAS_S):
                registrar("el panel no está: reabriéndolo")
                abrir_panel(a, procesos, inicios)
                ultima_apertura[0] = time.time()
            if (not a.sin_overlay and not en_silencio()
                    and overlay_vivo() is None):
                registrar("el overlay no está: reabriéndolo")
                abrir_overlay(procesos, inicios)
        elif not abierto and dentro:
            dentro = False
            registrar("Deadlock cerrado: cerrando y archivando")
            for p in procesos:
                try:
                    p.terminate()
                except OSError:
                    pass
            procesos = []
            time.sleep(3)
            try:
                salida = subprocess.run(
                    [sys.executable, os.path.join(RAIZ, "herramientas", "archivar.py")],
                    cwd=RAIZ, capture_output=True, text=True, timeout=120)
                for linea in (salida.stdout or "").strip().splitlines()[-4:]:
                    registrar("  " + linea)
            except (OSError, subprocess.SubprocessError) as exc:
                registrar(f"  el archivado falló: {exc}")
            lanzar_nota()
        time.sleep(max(2.0, a.intervalo))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nmodo espera terminado")

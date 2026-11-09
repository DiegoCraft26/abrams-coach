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
import os
import signal
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

LOG = "/tmp/abrams-vigilar.log"
PANEL_LOG = "/tmp/abrams-panel.log"
PUERTO = 8090


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


def revisar_hijos(procesos):
    """Anota los hijos que ya terminaron y devuelve los que siguen vivos."""
    vivos = []
    for p in procesos:
        codigo = p.poll()
        if codigo is None:
            vivos.append(p)
        else:
            registrar(f"{os.path.basename(p.args[1] if len(p.args) > 1 else p.args[0])} "
                      f"(pid {p.pid}) terminó: {describir_fin(codigo)}")
    return vivos


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


def panel_vivo():
    """PID del panel si sigue vivo. Sirve para no abrir dos y para reabrirlo si muere."""
    try:
        with open("/tmp/abrams-panel.pid", encoding="utf-8") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
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
            with open("/tmp/abrams-panel.pid", "w", encoding="utf-8") as f:
                f.write(str(pid))
            return pid
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def abrir_panel(a, procesos):
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
    time.sleep(2)
    subprocess.run(
        [sys.executable, os.path.join(RAIZ, "herramientas", "colocar_panel.py")],
        cwd=RAIZ, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, timeout=20)


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
    ap.add_argument("--intervalo", type=float, default=5.0)
    a = ap.parse_args()

    registrar("modo espera: abre Deadlock cuando quieras")
    procesos = []
    dentro = False
    while True:
        procesos = revisar_hijos(procesos)
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
                    procesos.append(subprocess.Popen(
                        orden, cwd=RAIZ, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL))
                else:
                    registrar("el coach ya estaba corriendo en :8090")
                if not a.sin_panel and panel_vivo() is None:
                    abrir_panel(a, procesos)
            except (OSError, subprocess.SubprocessError) as exc:
                registrar(f"no pude arrancar: {exc}")
        elif abierto and dentro and not a.sin_panel:
            # El panel es de solo mirar: si se cierra o se cae, se reabre solo. Sin
            # botones, sin atajos y sin que tengas que tocar nada.
            if panel_vivo() is None:
                registrar("el panel no está: reabriéndolo")
                abrir_panel(a, procesos)
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
        time.sleep(max(2.0, a.intervalo))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nmodo espera terminado")

"""¿La app que está abierta corre el código que tengo?

El panel no se recarga solo: cuando se toca código y no se reinicia, la ventana
sigue mostrando la versión anterior sin avisar. Este módulo responde esa duda con
tres datos medibles en vez de memoria:

1. el commit/rama/huella del código en disco (`estado_git`, `huella`),
2. el commit/huella con el que arrancó la app (`marcar_arranque` lo escribe al
   levantar el servidor; `leer_marcador` lo lee),
3. el remoto, para saber si además falta `git pull`.

`comparar()` junta todo y da un veredicto. Sin marcador (instancia anterior a
este módulo) cae al arranque real del proceso leído de /proc y a la fecha de la
última modificación: menos exacto, pero dice «probable».
"""
import hashlib
import json
import os
import subprocess
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: `ABRAMS_VERSION_MARCADOR` permite que una instancia de prueba (otro puerto) no
#: pise el marcador de la app de verdad.
MARCADOR = os.environ.get("ABRAMS_VERSION_MARCADOR") or os.path.join(
    RAIZ, "salida", "version-en-vivo.json")

#: Rutas cuyo contenido define la versión. Tests, datos y salidas no cuentan.
FIJAS = ("run.py", "panel_nativo.py", "config/coach.yaml")


def rutas_fuente():
    """Rutas relativas que forman el código del coach (determinista y ordenado)."""
    rutas = [r for r in FIJAS if os.path.exists(os.path.join(RAIZ, r))]
    base = os.path.join(RAIZ, "coach")
    for carpeta, subcarpetas, ficheros in os.walk(base):
        subcarpetas[:] = sorted(d for d in subcarpetas if d != "__pycache__")
        for fichero in sorted(ficheros):
            if fichero.endswith(".py"):
                rutas.append(os.path.relpath(os.path.join(carpeta, fichero), RAIZ))
    return sorted(set(rutas))


def huella(rutas=None):
    """sha256 del contenido de esas rutas: cambia con cualquier edición."""
    h = hashlib.sha256()
    for relativa in rutas if rutas is not None else rutas_fuente():
        ruta = relativa if os.path.isabs(relativa) else os.path.join(RAIZ, relativa)
        try:
            with open(ruta, "rb") as f:
                contenido = f.read()
        except OSError:
            continue
        h.update(relativa.encode())
        h.update(b"\0")
        h.update(hashlib.sha256(contenido).digest())
    return h.hexdigest()[:16]


def _git(*args):
    """Salida de git o None si no hay git o el comando falla (copia exportada)."""
    try:
        r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True,
                           text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def estado_git():
    """Lo que dice git del código en disco, sin lanzar si el repo no existe."""
    commit = _git("rev-parse", "--short", "HEAD")
    if commit is None:
        return {"git": False, "commit": None, "rama": None, "sucio": None,
                "fecha": None, "remoto": None}
    completo = _git("rev-parse", "HEAD")
    rama = _git("rev-parse", "--abbrev-ref", "HEAD")
    sucio = _git("status", "--porcelain")
    fecha = _git("log", "-1", "--format=%ci")
    remoto = None
    cuenta = _git("rev-list", "--left-right", "--count", "HEAD...@{u}")
    if cuenta:
        adelante, atras = (int(x) for x in cuenta.split()[:2])
        remoto = {"adelante": adelante, "atras": atras,
                  "al_dia": adelante == 0 and atras == 0,
                  "upstream": _git("rev-parse", "--abbrev-ref", "@{u}")}
    return {
        "git": True, "commit": commit, "commit_completo": completo, "rama": rama,
        "sucio": bool(sucio), "sucio_detalle": sucio.splitlines()[:20] if sucio else [],
        "fecha": fecha, "remoto": remoto, "huella": huella(),
    }


def arranque_iso():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def marcar_arranque(archivo=None):
    """Deja en disco con qué código arrancó esta instancia. Nunca debe romper el arranque."""
    destino = archivo or MARCADOR
    try:
        estado = estado_git()
        datos = {
            "arranque": arranque_iso(),
            "pid": os.getpid(),
            "commit": estado["commit"],
            "rama": estado["rama"],
            "huella": estado["huella"],
            "sucio": estado["sucio"],
            "version": leer_version(),
        }
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        with open(destino, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        return datos
    except OSError:
        return None


def leer_marcador(archivo=None):
    try:
        with open(archivo or MARCADOR, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def leer_version():
    """Primera línea de CHANGELOG («## v0.7.2 — fecha»), la versión declarada."""
    try:
        with open(os.path.join(RAIZ, "CHANGELOG.md"), encoding="utf-8") as f:
            for linea in f:
                if linea.startswith("## v"):
                    return linea[3:].split("—")[0].strip()
    except OSError:
        pass
    return None


def _inicio_proceso(pid):
    """Epoch de arranque del proceso, vía /proc/stat btime + starttime en jiffies."""
    try:
        with open("/proc/stat", encoding="utf-8") as f:
            btime = next(int(l.split()[1]) for l in f if l.startswith("btime"))
        with open("/proc/%s/stat" % pid, encoding="utf-8") as f:
            campos = f.read().rsplit(")", 1)[1].split()
        return btime + int(campos[19]) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def procesos_en_vivo():
    """Instancias de run.py cuyo cwd es este repo (puede haber una sola)."""
    vivos = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode(errors="replace").strip()
            cwd = os.readlink("/proc/%s/cwd" % pid)
        except OSError:
            continue
        if "run.py" in cmd and os.path.realpath(cwd) == RAIZ:
            vivos.append({"pid": int(pid), "cmd": cmd,
                          "inicio": _inicio_proceso(pid)})
    return vivos


def _mtime_mas_nuevo():
    ultimo = 0.0
    for relativa in rutas_fuente():
        try:
            ultimo = max(ultimo, os.path.getmtime(os.path.join(RAIZ, relativa)))
        except OSError:
            continue
    return ultimo


def _vivo(pid):
    """¿Sigue existiendo ese pid y es un run.py de este repo? Evita PIDs reciclados."""
    try:
        with open("/proc/%s/cmdline" % pid, "rb") as f:
            cmd = f.read().replace(b"\0", b" ").decode(errors="replace")
        cwd = os.readlink("/proc/%s/cwd" % pid)
    except OSError:
        return False
    return "run.py" in cmd and os.path.realpath(cwd) == RAIZ


def comparar():
    """Veredicto: ¿lo que corre es lo que está en disco y es lo último que tenemos?"""
    actual = estado_git()
    actual["version"] = leer_version()
    marcador = leer_marcador()
    procesos = procesos_en_vivo()

    aviso = None
    if marcador and marcador.get("pid") and not _vivo(marcador["pid"]):
        aviso = ("el marcador es de una instancia que ya no corre (pid %s)"
                 % marcador["pid"])
        marcador = None
    if marcador:
        corrido = {"commit": marcador.get("commit"), "huella": marcador.get("huella"),
                   "rama": marcador.get("rama"), "sucio": marcador.get("sucio"),
                   "arranque": marcador.get("arranque"), "pid": marcador.get("pid"),
                   "version": marcador.get("version"), "fuente": "marcador"}
    elif procesos:
        proceso = min(procesos, key=lambda p: p["inicio"] or 0)
        corrido = {"commit": None, "huella": None, "rama": None, "sucio": None,
                   "arranque": (time.strftime("%Y-%m-%d %H:%M:%S",
                                              time.localtime(proceso["inicio"]))
                                if proceso["inicio"] else None),
                   "pid": proceso["pid"], "version": None, "fuente": "proceso"}
        aviso = ("sin marcador de arranque (instancia anterior a esta herramienta): "
                 "se deduce por la hora del proceso y la fecha de los archivos")
    else:
        corrido = None

    igual_huella = bool(corrido and corrido.get("huella")
                        and corrido["huella"] == actual["huella"])
    igual_commit = bool(corrido and corrido.get("commit")
                        and corrido["commit"] == actual["commit"])

    if corrido is None:
        veredicto, texto = "sin_app", "no hay app abierta de este repo"
    elif actual["git"] and corrido["fuente"] == "marcador":
        if igual_huella and igual_commit:
            veredicto, texto = "si", "la app abierta corre el código actual"
        else:
            veredicto, texto = "no", "la app abierta quedó atrás: reiníciala para que cargue el código nuevo"
    elif corrido["fuente"] == "proceso":
        inicio = None
        if procesos:
            inicio = min((p["inicio"] or 0) for p in procesos)
        ultimo = _mtime_mas_nuevo()
        if inicio and inicio >= ultimo:
            veredicto, texto = "probable_si", ("el proceso arrancó después del último cambio de "
                                              "código: corre lo actual (deducido, no marcado)")
        else:
            veredicto, texto = "probable_no", ("el código se tocó después de abrir la app: "
                                               "queda vieja hasta reiniciarla")
    else:
        veredicto, texto = "sin_git", "no hay repo git: sólo se puede comparar por huella"

    remoto = actual.get("remoto")
    if remoto and not remoto["al_dia"]:
        texto += " · además el repo local %s frente a %s" % (
            "está %d commits adelante" % remoto["adelante"] if remoto["adelante"]
            else "va %d commits atrás" % remoto["atras"], remoto["upstream"])

    return {
        "veredicto": veredicto,
        "texto": texto,
        "aviso": aviso,
        "actual": actual,
        "corriendo": corrido,
        "procesos": procesos,
        "arranque_marcado": marcador,
        "ahora": arranque_iso(),
    }


def resumen(datos=None):
    """Texto corto para terminal y para el pie del panel."""
    d = datos or comparar()
    a, c = d["actual"], d["corriendo"]
    lineas = []
    if c:
        lineas.append("app abierta : %s · %s · arrancó %s%s" % (
            c.get("commit") or "sin commit", c.get("rama") or "sin rama",
            c.get("arranque") or "sin fecha",
            (" · pid %s" % c["pid"]) if c.get("pid") else ""))
    else:
        lineas.append("app abierta : ninguna")
    lineas.append("código disco: %s · %s · %s%s" % (
        a.get("commit") or "sin commit", a.get("rama") or "sin rama",
        "con cambios sin commitear" if a.get("sucio") else "limpio",
        (" · huella %s" % a["huella"]) if a.get("huella") else ""))
    if a.get("remoto"):
        r = a["remoto"]
        lineas.append("remoto      : %s · %s" % (
            r["upstream"], "al día" if r["al_dia"] else
            "local adelante %d / atrás %d" % (r["adelante"], r["atras"])))
    lineas.append("veredicto   : %s — %s" % (d["veredicto"], d["texto"]))
    if d.get("aviso"):
        lineas.append("aviso       : %s" % d["aviso"])
    return "\n".join(lineas)

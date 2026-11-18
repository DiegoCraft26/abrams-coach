# Versión: ¿la app abierta es la última?

**Respuesta corta:** ahora se comprueba en un comando; antes no se podía comprobar,
solo recordar. Y no, no se actualiza siempre sola: el panel no se recarga en
caliente, así que la regla es reiniciar después de tocar código.

```bash
python3 herramientas/version.py          # veredicto y datos
python3 herramientas/version.py --json   # lo mismo, crudo
python3 herramientas/version.py --subir  # git pull --ff-only y vuelve a comparar
```

Sale **0** si la app abierta corre el código actual y **2** si quedó atrás, así que
sirve de puerta en un script o en un cron.

También está en vivo mientras la app corre:

```bash
curl -s http://127.0.0.1:8090/api/version | python3 -m json.tool
```

## Qué compara

Tres cosas distintas, que es lo que evita confundirse:

| Pregunta | Dato | De dónde sale |
|---|---|---|
| ¿Qué código hay en disco? | commit corto, rama, limpio/sucio, huella sha256 de los `.py` | `git` + `coach/version.py` |
| ¿Con qué código arrancó la app? | commit y huella del arranque | `salida/version-en-vivo.json`, escrito por `servidor.arrancar()` |
| ¿Es además lo último que tenemos? | `origin/master`: al día, adelante o atrás | `git rev-list --left-right --count HEAD...@{u}` |

La **huella** existe porque un commit no lo cuenta todo: si editas `coach/motor.py` y
no commiteas, el commit sigue siendo el mismo y el panel ya es otro. La huella cambia
con cualquier byte de los archivos que definen el comportamiento (`coach/**/*.py`,
`run.py`, `panel_nativo.py`, `config/coach.yaml`). Tests, datos y salidas no entran.

Veredictos posibles: `si`, `no`, `probable_si`, `probable_no` (instancia sin marcador,
deducida por la hora del proceso y la fecha de los archivos), `sin_app`, `sin_git`.

## Por qué la app no se actualiza sola

El panel y el motor se arman **al arrancar**: `run.py` carga el conocimiento, monta el
motor, levanta el servidor y recién entonces pinta. Python deja los módulos en memoria;
no hay recarga en caliente ni watcher de archivos, y no la va a haber (el coach lee el
HUD a 14 cuadros por segundo; recargar módulos en medio de una partida es peor que
reiniciar).

Desde la v0.7.1, cerrar la ventana del panel apaga el coach que esa ventana arrancó
(`partida.sh prep pegado`). Eso hace que "abrir la app" sea de verdad "cargar el código
de ahora", siempre que se abra de cero.

El caso que engaña es el otro: dejar la app abierta de una sesión anterior, editar y
volver a mirar el panel. Ahí el panel muestra la versión vieja **sin avisar**. Eso es
exactamente lo que detecta `herramientas/version.py`.

## La regla

> Si tocas código del coach, reinicia la app antes de creerle al panel.
> Si no la reinicias, el panel miente.

Formas de reiniciar:

```bash
herramientas/partida.sh prep pegado   # modo app: la ventana manda y al cerrarla se apaga
herramientas/arrancar.sh vivo         # en segundo plano, para terminal
```

`arrancar.sh` ya mata el PID anterior (`/tmp/abrams-coach.pid`) y rota el log. Dos
instancias a la vez no pueden: el puerto 8090 es de la primera.

## Qué **no** hace esto

- No hace `git pull` solo: `--subir` es explícito. Un pull silencioso en medio de una
  sesión de ranked es cómo se mezclan versiones sin querer.
- No reinicia la app solo. El aviso está, la decisión es tuya.
- No vigila la copia de la PC (`pcserver`): ahí el repo es el mismo y el bot de
  mantenimiento commitea a `master`; para saber si divergió, `ssh pc 'cd abrams-coach &&
  git log --oneline -3'`.

## Estado verificado el 2026-11-18 01:10

| Dónde | Versión |
|---|---|
| App abierta (`run.py --fuente vivo`, pid 759485, arrancó 01:09:53) | código de `b1fb1f8`, sin cambios locales |
| Repo local (`~/Desktop/Chat/abrams-coach`) | `b1fb1f8` · `master` · limpio |
| Remoto (`origin/master`, GitHub privado) | `b1fb1f8`, al día |
| Copia de la PC (`pcserver:~/abrams-coach`) | `b1fb1f8`, limpio |

Conclusión de ese día: **sí, la app abierta era la más reciente**. La comprobación fue
por inspección (arranque posterior a la última edición) porque todavía no existía el
marcador; a partir de este cambio la respuesta sale de `/api/version`.

## Dónde está cada pieza

- `coach/version.py` — huella, estado de git, marcador de arranque, veredicto.
- `coach/servidor.py` — `/api/version` y la llamada a `marcar_arranque()` al arrancar.
- `herramientas/version.py` — la CLI de arriba.
- `tests/test_version.py` — la lógica del veredicto, sin depender de git.
- `salida/version-en-vivo.json` — el marcador (ignorado por git; es de la máquina).

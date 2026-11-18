# Bot de mantenimiento

Corre en la PC headless (`pcserver`) con cron, dos veces al día (04:15 y 16:15).

## Qué hace

1. `git reset --hard origin/master` — la rama del bot es desechable.
2. `ruff check --select F401,F841 --fix` — imports y variables sin usar. Nada más:
   son las únicas reglas que no cambian comportamiento.
3. `pytest -q`. Compara los fallos con `~/.abrams-bot/baseline.txt`.
   **Si aparece un fallo nuevo, revierte todo y no commitea.**
4. Si no hay fallos nuevos y hay cambios: rama `bot/AAAA-MM-DD`, commit y push.
   Nunca toca `master`.

## Por qué hay una línea base

La PC no reproduce el entorno del desktop (Python 3.10 contra 3.14, numpy 2.2 contra
2.5). Dos pruebas de visión fallan allí y pasan aquí. El bot vigila **no empeorar**,
no "todo verde": un gate que exige 100% en una máquina distinta sólo produce ruido.

## Instalación (ya hecha en pcserver el 2026-11-17)

```bash
# llave de despliegue con escritura, sólo para este repo
ssh-keygen -t ed25519 -N "" -f ~/.ssh/abrams_bot
# (alta en GitHub como deploy key read-write)

# entorno aparte, sin tocar el python del sistema
python3 -m venv /srv/scratch/abrams-bot-venv
/srv/scratch/abrams-bot-venv/bin/pip install pytest ruff "Pillow>=10" "numpy>=1.26" "PyYAML>=6"

# el script vive fuera del repo para que un reset --hard no lo borre
install -m 755 mantenimiento.py ~/.abrams-bot/mantenimiento.py

# cron
15 4,16 * * * /srv/scratch/abrams-bot-venv/bin/python $HOME/.abrams-bot/mantenimiento.py >> $HOME/.abrams-bot/cron.log 2>&1
```

## Cómo se apaga

```bash
crontab -l | grep -v mantenimiento.py | crontab -
```

## Lo que este bot NO hace

No toca lógica del motor, no cambia umbrales, no actualiza datos, no fusiona nada.
Un agente con criterio puede proponer más; esto es lo que se puede automatizar sin que
alguien revise el resultado cada mañana.

# Informe — Fases 0 a 3 (2026-11-09)

Lo que se hizo, cómo se comprobó y qué sigue sin poder afirmarse. Cada cifra sale de una
medición con la API real o de una prueba en la suite; donde no hay medición, se dice.

## Fase 0 · Estabilidad

| Qué | Cómo se comprobó | Resultado |
|---|---|---|
| El panel moría sin dejar rastro | `coach/diagnostico.py`: `faulthandler`, excepthook de hilo, señales y volcado con `kill -USR1` | `/tmp/abrams-panel-crash.log` registra arranque, señal y «salida limpia»; el 09-11 a las 13:27 quedó anotado el final real |
| La causa de la muerte silenciosa | `/proc/<pid>/stat` + línea de órdenes | era un **zombi**: `os.kill(pid, 0)` contestaba como si viviera y el vigilante no reabría el panel |
| El vigilante se caía y nadie lo levantaba | servicio `systemd --user` con `Restart=always` | maté el proceso a propósito: «restart counter is at 1», volvió en 10 s |
| Dos vigilantes abriendo ventanas | bloqueo `flock` en `/tmp/abrams-vigilar.lock` | el segundo proceso sale; probado en suite |
| La ventana se llevaba el foco y sacaba a Diego del juego | `set_visible` en vez de `present`, `set_can_focus(False)`, KWin: debajo y sin barra | prueba de regresión sobre `coach/ui/app.py` |
| Estado perdido al reiniciar el coach | `coach/estado_guardado.py` + `/api/estado` | sirve lo último con su edad y `origen: "guardado"` (9 pruebas) |
| Interruptor del usuario | `touch ~/.abrams-silencio` | el vigilante espera sin abrir el panel (probado) |

Herramienta: `python3 herramientas/revisar_estabilidad.py` → veredicto en 5 s. En la
instancia real: coach y panel con 23 min de vida, sin reinicios, veredicto sano.

## Fase 1 · Visión bajo demanda

Medido con la API real (detalle en `docs/vision-mediciones.md`):

| Formato | Peso | Latencia | Tokens | Qué lee |
|---|---|---|---|---|
| Cuadro del juego 640 px | 33 kB | 23 s | ~3 600 | fase; **no** el reloj |
| Recorte 768–1024 px | 46–85 kB | timeout | — | nada: no vuelve |
| Solo el reloj | 0.9 kB | 1.3 s | 314 | `reloj_s` correcto |
| Tira del HUD | 10 kB | 24–40 s | 650–1 000 | reloj, oro, almas de equipo e ítems visibles, **los cuatro correctos** |

- `chat_vision()` (data URL de OpenAI) con `RespaldoVision`: huggingface primero,
  commandcode de respaldo, el Qwen local fuera (no ve).
- Cola con una sola petición en vuelo, prioridad para tienda y marcador, tope de 300
  cuadros por partida con aviso al 70 %, caché por hash.
- Skill `deadlock-vision` en `~/.dsh/skills/deadlock-vision/` con reglas, esquema y
  3 ejemplos.

**Límite honesto:** con este proveedor, «latencia < 3 s por cuadro» no se cumple
(1.3–40 s). El diseño lo asume: la visión va en cola y el panel nunca la espera.

## Fase 2 · Inventario y espectador

- `coach/inventario_propio.py`: ítems con fuente, confianza y hora; **guardia de
  espectador** (mirar la partida de otro no toca tu inventario); aviso «abre B» a los
  3 min; sobrevive a un reinicio.
- Con broadcast, comprar y vender se refleja en el estado publicado: probado (1 → 2
  ítems, 4 → 3 huecos libres) y en vivo los huecos salen 3/4, 1/4, 1/4.
- **Tienda (respaldo sin broadcast):** el modelo transcribe nombres y la traducción a id
  se hace en local contra `data/catalogo.json` — 10 de 10 resueltos en la primera
  lectura real. La primera versión devolvió el escaparate entero como inventario propio;
  ya se piden dos listas (`mios` y `se_venden`).
- Una compra dispara la lectura de tienda en el acto y la cadencia se adapta (abierta
  cada 2 lecturas, cerrada cada 8).

**Sin verificar en vivo:** una lectura positiva con la tienda abierta y el prompt nuevo.
Solo ocurre en partidas sin broadcast, y desde las 14:21 Diego juega con broadcast, donde
la visión no interviene a propósito.

## Fase 3 · Identidad de partida

- El `console.log` del juego trae el match id en esta build y coincide con el del HUD:
  cuando coinciden, el coach decide **sin llamar a la API** (`via: hud+log`) y no gasta
  cuota de espectador.
- Si discrepan, manda el texto del log y la lectura de imagen queda como rechazo.
- `coach/telemetria.py` + `/api/identidad`: cada decisión apuntada (vía, candidato,
  motivo, rechazo). En la sesión: 119 decisiones, vías `hud+log` 45 · `hud` 37 ·
  `cuenta` 21 · `log` 10, con 16 rechazos.
- Nunca una partida falsa: con dos ids que no se pueden validar, el estado dice «sin
  datos» y muestra fase y héroe del juego.

## Herramientas que quedaron

```bash
python3 herramientas/revisar_estabilidad.py    # ¿está sano ahora?
python3 herramientas/resumen_partida.py        # qué pasó en la última partida
python3 herramientas/medir_vision_zonas.py --enviar   # recortes + lectura por zona
python3 tests/test_invariantes.py              # 6/6
PYTHONPATH=$HOME/.dsh/bin/pylib python3 -m pytest -q
```

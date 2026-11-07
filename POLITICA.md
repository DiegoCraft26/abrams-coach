# Política de la app: qué hace, qué no hace y por qué

Esta app **no está respaldada por Valve**. Trabaja fuera del juego: captura la pantalla del
escritorio y consulta una API pública de terceros. Nada de lo que hace toca el proceso de
Deadlock.

Base: `informes/investigacion-reglas-y-anticheat.md` (25 fuentes, consultadas el
2026-11-07), principalmente el [Acuerdo de Suscripción de Steam](https://store.steampowered.com/subscriber_agreement/?l=english)
§4.B/§4.C, la [FAQ de VAC](https://help.steampowered.com/en/faqs/view/571A-97DA-70E9-FF74)
y la [wiki de VAC](https://developer.valvesoftware.com/wiki/Valve_Anti-Cheat).

## Lo que la app hace

| Acción | Riesgo documentado |
|---|---|
| Capturar el escritorio con `spectacle` (herramienta del sistema, igual que OBS) | bajo |
| Recortar y leer esos píxeles con OCR y plantillas | bajo (es lo mismo que hace un humano mirando) |
| Consultar `api.deadlock-api.com` por HTTP, sin credenciales del juego | bajo |
| Mostrar recomendaciones en una ventana aparte, en el otro monitor | bajo |

## Lo que la app no hace, y no se va a implementar

| Prohibido | Por qué |
|---|---|
| Leer memoria del proceso de Deadlock o de Steam | SSA §4.B; Valve baneó ~40 000 cuentas de Dota 2 con una trampa de memoria en 2023 |
| Inyectar DLLs, hooks o overlays dentro del juego | VAC lo detecta; es la vía clásica de ban |
| Automatizar input (macros, auto-compra, clics) | SSA §4.C |
| Modificar ejecutables o assets del juego | rompe la verificación de integridad |
| Usar la *ingest tool* de deadlock-api | esa herramienta sí lee memoria del cliente: es de ellos, no nuestra, y no la ejecutamos |
| Mostrar información que el juego no muestre en pantalla | si no está en el HUD o el marcador, no se usa |
| Falsificar estadísticas, XP o progreso | SSA §4.C |

## Regla de información visible

Todo lo que la app muestra sale de dos sitios: **píxeles que el juego ya pinta** (reloj,
oro, marcador, compras) o **el broadcast público de espectador**. Si un dato no está en
ninguno de los dos, la app dice que no lo tiene. No hay lectura de archivos del juego, ni
de la caché de Steam, ni del tráfico de red.

## Zona gris que se evita por diseño

- **Overlays tipo Overwolf**: operan con permiso de Overwolf, no de Valve. No se integran.
- **Mods de HUD**: no hay confirmación de compatibilidad con VAC. No se usan.
- **Redistribución de datos del broadcast**: la API es comunitaria; la app no redistribuye
  nada, solo consulta.

## Si Valve publica una política específica para Deadlock

Se adapta o se retira la función que corresponda. La app está partida en módulos
precisamente para eso: apagar `fuentes.hud` o el modo vivo no rompe el resto.

## Cómo se comprueba que esto se cumple

```bash
# ninguna referencia a memoria, hooks, inyección o input sintético en el código
grep -riE "ptrace|ReadProcessMemory|/proc/[0-9]+/mem|LD_PRELOAD|libvulkan_layer|xdotool|ydotool|uinput" \
  coach/ run.py panel_nativo.py herramientas/ || echo "sin coincidencias"

# la única captura es spectacle (herramienta del sistema)
grep -rn "spectacle" coach/ | head
```

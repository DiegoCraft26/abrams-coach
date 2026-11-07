# Guía de uso

Para jugar, no para programar. Si algo de aquí no coincide con lo que ves, abre un issue
con la captura y la versión (`abrams-coach estado`).

## Antes de la primera partida

1. Instala: `./instalar.sh`. Te dice si falta algo.
2. Comprueba que el panel abre: `abrams-coach demo`. Debe aparecer una ventana con un
   panel oscuro, un reloj y una recomendación.
3. Coloca la ventana en el segundo monitor. El tamaño y la posición se recuerdan solos.

## Durante la partida

```bash
abrams-coach jugar
```

Eso apaga lo que roba memoria de video, arranca el coach y abre el panel. El juego se abre
como siempre; la app no lo toca.

Lo que vas a ver, de arriba abajo:

- **Insignia**: `en vivo` mientras el broadcast manda datos; `datos congelados` con la edad
  cuando deja de llegar.
- **Reloj, oro y patrimonio**: el reloj y el oro salen de tu pantalla (van con ~medio
  segundo de retraso). El resto, del broadcast (20–25 s).
- **Compra**: un ítem, su coste y dos razones. Si no te alcanza, dice cuánto falta.
- **Inventario**: tus 12 slots. Verde significa que el ítem rinde más de lo esperado para
  su minuto de compra; rojo, menos.
- **Enemigos**: almas y KDA. La barra compara almas entre ellos, no contigo.
- **Plan**: las dos compras que suelen seguir a la recomendada según las partidas reales.
- **Contra su composición**: ítems que la amenaza enemiga justifica. Van aparte porque sus
  números propios son malos; úsalo como aviso, no como orden.
- **Ventas**: solo aparece cuando vender mejora la decisión.
- **Pie**: `motor 4 ms · captura 450 ms · lectura 127 ms · TV 22 s atrás`. Si algo se pone
  lento, se ve aquí.

Atajos: `1` compra, `2` enemigos, `3` compras, `?` ayuda, `Esc` cierra.

## Al terminar

```bash
abrams-coach archivar     # guarda la sesión en la base local
abrams-coach informe      # escribe informes/partidas/<match>.md
```

El informe trae números y hallazgos. Los hallazgos los calcula la app (compra tardía,
tiempo en FARM, repetición de recomendaciones); el modelo solo los redacta. Si no hay
modelo disponible, el informe sale igual con los números.

## Problemas frecuentes

| Síntoma | Qué mirar |
|---|---|
| `sin partida` | el juego no está abierto, o tu cuenta no está en la partida |
| `datos congelados` | el broadcast dejó de mandar; suele volver solo en unos segundos |
| El reloj no cuadra | la caja del reloj depende de la resolución: recalibra con `docs/ARQUITECTURA.md` |
| El oro sale mal | el HUD se movió; activa la detección por color (`fuentes.hud.color_oro`) |
| No aparece la recomendación | fase inicial (antes del minuto 10) o ningún ítem pasa el filtro |
| El panel va lento | mira el pie; si `captura` sube de 600 ms, algo más está capturando pantalla |

## Qué no hace

No lee memoria del juego, no inyecta nada, no automatiza clics y no muestra nada encima del
juego. Detalle y fuentes: [`POLITICA.md`](../POLITICA.md).

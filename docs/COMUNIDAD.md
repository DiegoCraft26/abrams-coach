# Para presentarlo en la comunidad (y lo que hay que decir de frente)

Texto pensado para Discord/foros. La regla: **no prometer nada que no esté medido**. Si lo
publicamos como «te encuentra la build rota», nos lo desmontan con un tracker público en el
primer día.

## Qué es, en un párrafo

> Abrams Coach es un panel que te dice **qué comprar ahora y qué viene después** en Deadlock,
> y después de cada partida te devuelve tres números: cuándo llegó tu primer ítem de 3 200,
> cuántas veces moriste y cuánto participaste en peleas. Funciona en un segundo monitor o
> como una tarjeta encima del HUD. No lee memoria del juego, no inyecta nada y no toca tu
> cuenta.

## Qué hace

- **Antes de jugar**: `abrams-coach plan` resume tus últimas ranked contra dos metas
  medidas (y una referencia) y te propone un objetivo para la sesión.
- **Durante**: el camino de compra del héroe, la amenaza de la composición enemiga y un
  aviso cuando pasas de 6 muertes o bajas de 0.40 de participación.
- **Después**: la nota de la partida, con tu perfil contra el histórico de 3 538 partidas.
- **Sin partida**: el panel te recuerda cómo fue la última.

## Qué NO hace (y conviene decirlo antes de que lo pregunten)

- **No recomienda ítems por «valor medido»**. Lo intentamos con 20 parches y 63 680 compras
  y ningún ítem tiene un efecto demostrado: el ranking no replica ni entre parches ni dentro
  del mismo periodo. El panel no enseña esa evidencia a propósito.
- **No lee memoria, no inyecta, no engancha el proceso del juego.** El overlay es una
  ventana del compositor, como un panel del escritorio.
- **No sabe tu oro exacto en tiempo real.** Por eso no dice «te alcanza»: las almas llegan
  con retraso y fingir precisión costaba credibilidad.
- **Windows todavía no.** Está diseñado y escrito el backend de captura, pero sin una máquina
  Windows no se ha medido nada. Hoy es Linux + KDE.

## Mensaje corto para el canal

> Hola. Hice un panel para Deadlock que te dice qué comprar y después te da una nota de la
> partida con tres números: primer 3 200, muertes y participación. Está medido en 3 538
> partidas: con 6 muertes o menos se gana ~77 % y con 0.40 de participación ~71 %. No lee
> memoria ni inyecta nada; es un panel en el segundo monitor (o una tarjeta encima del HUD).
> Por ahora solo Linux/KDE. Lo que **no** hace: recomendarte ítems por «valor medido», porque
> con los datos disponibles ningún ítem pasa la prueba. ¿Alguien lo quiere probar y me dice
> qué se rompe?

## Lo que hay que pedir a quien lo pruebe

1. **Qué se rompe**: capturas, errores, el log de `/tmp/abrams-coach.log`.
2. **Si el panel y el overlay aparecen** en el segundo monitor y sobre el juego.
3. **Si la nota sale** al terminar una partida (y si dice «demo no disponible», que es
   normal en las primeras horas).

Con eso se arregla más en una tarde que con diez ideas nuevas.

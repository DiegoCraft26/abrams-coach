"""Explicador: las razones que ve el jugador, en orden de utilidad.

Antes las razones se armaban dentro del bucle de candidatos, así que cualquier ítem sin
señal fuerte salía sin explicación (invariante 5 del QA) y el panel mostraba "sin datos",
que parece un fallo de lectura. Aquí la explicación es una función aparte: recibe las
señales ya calculadas y siempre devuelve al menos una razón, con el dato que la sostiene.
"""
from . import patrones


def razones(residual=0.0, counter=0.0, pareja=0.0, cadena=0.0, info_fase=None,
            min_compra=None, distancia_t=None, requiere_venta=False, slot="",
            contexto=None, presupuesto=None, t_s=None, almas=None, faltan_fase=None):
    """Lista de razones legibles. Nunca vacía."""
    salida = []

    if residual and residual > 0:
        salida.append(f"{residual*100:+.1f}pp mejor de lo esperado para su minuto de compra")
    if counter and counter > 0.01:
        salida.append(f"{counter*100:+.1f}pp en este matchup (datos de 1.9 M de partidas)")
    if pareja and pareja > 0.005:
        salida.append(f"combo con lo que ya tienes (+{pareja*100:.1f}pp)")
    if cadena and cadena > 0.15:
        salida.append(f"suele ser la compra siguiente ({cadena*100:.0f}% de las veces)")
    if info_fase:
        salida.append(f"se compra en esta fase y gana {info_fase['wr_ajustado']*100:.1f}% "
                      f"(n={info_fase['n']:,})")
    if min_compra is not None and distancia_t is not None and distancia_t <= 6:
        salida.append(f"estás en su ventana de compra (minuto {min_compra:.0f} de partida)")
    if contexto:
        salida.append(contexto)
    if presupuesto:
        salida.append(presupuesto)
    if requiere_venta:
        salida.append(f"necesita vender algo del slot {slot}")

    # Contexto de fase económica: ayuda a decidir cuándo parar de ahorrar.
    if t_s is not None and almas is not None:
        fase = patrones.fase_economica(almas)
        hito = patrones.hito_siguiente(almas)
        desvio = patrones.desvio(t_s, almas)
        if faltan_fase is not None and faltan_fase > 0 and hito:
            salida.append(f"fase de build {fase}: faltan {int(faltan_fase):,} almas "
                          f"para el siguiente hito")
        elif desvio is not None and desvio > 0:
            salida.append(f"vas {int(desvio):,} almas por delante del build de Abrams")

    if not salida:
        salida.append(f"lo mejor disponible ahora en {slot}: "
                      f"residual {residual*100:+.1f}pp, sin señal fuerte todavía")
    return salida


def explicar_estado(econ, tactico, t_s, almas):
    """Una línea de contexto para la tarjeta: fase de build y desvío del benchmark."""
    partes = []
    fase = patrones.fase_economica(almas)
    if fase != "DESCONOCIDA":
        partes.append(f"fase de build {fase} (por almas, no por minuto)")
    desvio = patrones.desvio(t_s, almas)
    if desvio is not None:
        if desvio >= 0:
            partes.append(f"{int(desvio):,} almas por delante del build")
        else:
            partes.append(f"{abs(int(desvio)):,} almas por debajo del build")
    if tactico.get("estado") == "FARM":
        faltan = abs((econ or {}).get("delta") or 0)
        partes.append(patrones.objetivo_farm(faltan, t_s))
    return " · ".join(partes)

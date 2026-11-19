"""El listado de emisiones es gratis y las partidas que salen ahí no gastan cupo.

Lo confirmó el operador de la API el 2026-11-18: `/v1/matches/live/urls` se puede pedir
«however often you want», y la llamada por partida de los ids que aparecen en él
**tampoco cuenta** contra las 6/hora.

Esto es la diferencia entre un coach que solo funciona para el que juega y uno que puede
seguir un broadcast entero sin gastar nada. Las pruebas fijan la regla en el código:

- con URL del listado, la escucha NO pide ficha de espectador (`especta=False`);
- la lista se refresca rápido porque es gratis, pero la URL de cada partida se cachea
  una hora, que es lo que la propia API cachea.
"""
from coach import en_vivo
from coach.fuentes import live_api

TV = "http://dist1-ord1.steamcontent.com/tv/123_456"


def test_con_url_del_listado_no_se_pide_ficha():
    escucha = en_vivo.Escucha(123, url_tv=TV)
    assert escucha.especta is False, "el listado ya nos dio la URL: no cuesta nada"
    assert "broadcast_url" in escucha._url()
    assert "match_id=" not in escucha._url()


def test_sin_url_del_listado_si_se_pide_ficha():
    escucha = en_vivo.Escucha(123)
    assert escucha.especta is True, "espectar por id sí gasta una de las 6/hora"
    assert "match_id=123" in escucha._url()


def test_la_lista_se_refresca_pronto_porque_es_gratis():
    # Gratis y con 100 req/s: no tiene sentido arrastrar media hora de retraso.
    assert live_api.LISTA_TTL_S <= 60.0


def test_la_url_de_cada_partida_se_cachea_una_hora():
    assert live_api.URL_TTL_S == 3600.0, "es lo que la API cachea: una hora"

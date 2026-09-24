from datetime import timedelta

import pytest

from bot_utilidades.lembretes import LembreteError, descrever, interpretar, ler_tempo


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("10m", timedelta(minutes=10)),
        ("45min", timedelta(minutes=45)),
        ("2h", timedelta(hours=2)),
        ("1h30m", timedelta(hours=1, minutes=30)),
        ("1d", timedelta(days=1)),
        ("1d12h", timedelta(days=1, hours=12)),
        ("90m", timedelta(minutes=90)),
        ("2H", timedelta(hours=2)),
    ],
)
def test_le_tempos_validos(texto, esperado):
    assert ler_tempo(texto) == esperado


@pytest.mark.parametrize("texto", ["", "10", "m", "dez minutos", "10s", "30m1h", "-5m"])
def test_recusa_tempos_invalidos(texto):
    with pytest.raises(LembreteError, match="Não entendi"):
        ler_tempo(texto)


def test_tempo_minimo():
    with pytest.raises(LembreteError, match="mínimo"):
        ler_tempo("0m")


def test_tempo_maximo():
    assert ler_tempo("7d") == timedelta(days=7)
    with pytest.raises(LembreteError, match="máximo"):
        ler_tempo("7d1m")


def test_interpreta_tempo_e_texto():
    assert interpretar(["10m", "tomar", "água"]) == (timedelta(minutes=10), "tomar água")


@pytest.mark.parametrize("palavras", [[], ["10m"]])
def test_sem_texto_mostra_como_usar(palavras):
    with pytest.raises(LembreteError, match="Use assim"):
        interpretar(palavras)


@pytest.mark.parametrize(
    ("tempo", "esperado"),
    [
        (timedelta(minutes=10), "10min"),
        (timedelta(hours=1, minutes=30), "1h30min"),
        (timedelta(minutes=90), "1h30min"),
        (timedelta(days=1, minutes=5), "1d5min"),
    ],
)
def test_descreve_tempo(tempo, esperado):
    assert descrever(tempo) == esperado

from datetime import datetime, timedelta, timezone

import pytest

from bot_utilidades.lembretes import (
    FUSO,
    LembreteError,
    descrever,
    descrever_horario,
    encurtar,
    interpretar,
    ler_numero,
    ler_tempo,
)


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
    assert ler_tempo("365d") == timedelta(days=365)
    with pytest.raises(LembreteError, match="máximo é 365 dias"):
        ler_tempo("365d1m")


def test_interpreta_tempo_e_texto():
    assert interpretar(["10m", "tomar", "água"]) == (timedelta(minutes=10), "tomar água")


def test_texto_longo_demais():
    assert interpretar(["10m", "a" * 500])[1] == "a" * 500
    with pytest.raises(LembreteError, match="até 500 caracteres"):
        interpretar(["10m", "a" * 501])


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


AGORA = datetime(2026, 9, 27, 10, 0, tzinfo=FUSO)


@pytest.mark.parametrize(
    ("momento", "esperado"),
    [
        (datetime(2026, 9, 27, 14, 30, tzinfo=FUSO), "às 14:30"),
        (datetime(2026, 9, 28, 8, 5, tzinfo=FUSO), "em 28/09 às 08:05"),
        (datetime(2027, 1, 2, 9, 0, tzinfo=FUSO), "em 02/01/2027 às 09:00"),
        # 02:30 em UTC do dia 28 ainda é 23:30 do dia 27 em Brasília.
        (datetime(2026, 9, 28, 2, 30, tzinfo=timezone.utc), "às 23:30"),
    ],
)
def test_descreve_horario(momento, esperado):
    assert descrever_horario(momento, AGORA) == esperado


@pytest.mark.parametrize(("palavras", "esperado"), [(["3"], 3), (["#12"], 12)])
def test_le_numero(palavras, esperado):
    assert ler_numero(palavras) == esperado


@pytest.mark.parametrize("palavras", [[], ["tres"], ["3", "4"], ["-3"], ["3.5"], ["#"]])
def test_numero_invalido_mostra_como_usar(palavras):
    with pytest.raises(LembreteError, match="Use assim: /cancelar"):
        ler_numero(palavras)


def test_encurta_textos_longos():
    assert encurtar("tomar água") == "tomar água"
    assert encurtar("a" * 40) == "a" * 40
    assert encurtar("a" * 41) == "a" * 39 + "…"
    assert len(encurtar("a" * 500)) == 40

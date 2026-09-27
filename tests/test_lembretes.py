from datetime import datetime, time, timedelta, timezone

import pytest

from bot_utilidades.lembretes import (
    FUSO,
    LembreteError,
    Pedido,
    confirmar,
    descrever,
    data_e_hora,
    descrever_horario,
    encurtar,
    interpretar,
    ler_horario,
    ler_numero,
    ler_tempo,
    proxima_vez,
)

AGORA = datetime(2026, 9, 27, 10, 0, tzinfo=FUSO)


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
    assert interpretar(["10m", "tomar", "água"], AGORA) == Pedido(
        AGORA + timedelta(minutes=10), "tomar água", tempo=timedelta(minutes=10)
    )


def test_texto_longo_demais():
    assert interpretar(["10m", "a" * 500], AGORA).texto == "a" * 500
    with pytest.raises(LembreteError, match="até 500 caracteres"):
        interpretar(["10m", "a" * 501], AGORA)


@pytest.mark.parametrize(
    "palavras", [[], ["10m"], ["18:30"], ["todo", "dia"], ["todo", "dia", "8:00"]]
)
def test_sem_texto_mostra_como_usar(palavras):
    with pytest.raises(LembreteError, match="Use assim"):
        interpretar(palavras, AGORA)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("8:00", time(8, 0)), ("08:05", time(8, 5)), ("18:30", time(18, 30)), ("0:00", time(0, 0)),
     ("23:59", time(23, 59))],
)
def test_le_horarios_validos(texto, esperado):
    assert ler_horario(texto) == esperado


@pytest.mark.parametrize("texto", ["24:00", "12:60", "99:99"])
def test_recusa_horarios_que_nao_existem(texto):
    with pytest.raises(LembreteError, match="não existe"):
        ler_horario(texto)


@pytest.mark.parametrize("texto", ["8h", "8", "8:0", "8:000", "oito", "18h30"])
def test_recusa_horarios_mal_escritos(texto):
    with pytest.raises(LembreteError, match="Não entendi o horário"):
        ler_horario(texto)


@pytest.mark.parametrize(
    ("horario", "esperado"),
    [
        (time(18, 30), datetime(2026, 9, 27, 18, 30, tzinfo=FUSO)),  # ainda vai chegar hoje
        (time(8, 0), datetime(2026, 9, 28, 8, 0, tzinfo=FUSO)),  # já passou: amanhã
        (time(10, 0), datetime(2026, 9, 28, 10, 0, tzinfo=FUSO)),  # é agora: amanhã
    ],
)
def test_proxima_vez(horario, esperado):
    assert proxima_vez(horario, AGORA) == esperado


def test_proxima_vez_usa_o_relogio_de_brasilia():
    # 01:00 em UTC do dia 28 ainda é 22:00 do dia 27 em Brasília.
    agora_utc = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)
    assert proxima_vez(time(23, 0), agora_utc) == datetime(2026, 9, 27, 23, 0, tzinfo=FUSO)


def test_proxima_vez_vira_o_ano():
    agora = datetime(2026, 12, 31, 22, 0, tzinfo=FUSO)
    assert proxima_vez(time(8, 0), agora) == datetime(2027, 1, 1, 8, 0, tzinfo=FUSO)


def test_interpreta_horario_fixo():
    assert interpretar(["18:30", "ligar", "pra", "mãe"], AGORA) == Pedido(
        datetime(2026, 9, 27, 18, 30, tzinfo=FUSO), "ligar pra mãe"
    )


@pytest.mark.parametrize("inicio", [["todo", "dia"], ["Todo", "Dia"]])
def test_interpreta_lembrete_diario(inicio):
    assert interpretar([*inicio, "8:00", "tomar", "remédio"], AGORA) == Pedido(
        datetime(2026, 9, 28, 8, 0, tzinfo=FUSO), "tomar remédio", diario=True
    )


def test_diario_precisa_de_horario():
    # "todo dia 10m" não faz sentido; o erro fala do horário, não do tempo.
    with pytest.raises(LembreteError, match="Não entendi o horário"):
        interpretar(["todo", "dia", "10m", "alongar"], AGORA)


def test_todo_dia_no_meio_do_texto_nao_e_diario():
    pedido = interpretar(["10m", "todo", "dia", "é", "assim"], AGORA)
    assert not pedido.diario
    assert pedido.texto == "todo dia é assim"


@pytest.mark.parametrize(
    ("palavras", "esperado"),
    [
        (["1h30m", "reunião"], "✅ Combinado! Daqui a 1h30min (às 11:30) eu te lembro: reunião"),
        (["2d", "boleto"], "✅ Combinado! Daqui a 2d (em 29/09 às 10:00) eu te lembro: boleto"),
        (["18:30", "ligar"], "✅ Combinado! Hoje às 18:30 eu te lembro: ligar"),
        (["9:15", "ligar"], "✅ Combinado! Amanhã às 09:15 eu te lembro: ligar"),
        (
            ["todo", "dia", "22:00", "remédio"],
            "✅ Combinado! Todo dia às 22:00 eu te lembro: remédio\nO primeiro é hoje.",
        ),
        (
            ["todo", "dia", "8:00", "remédio"],
            "✅ Combinado! Todo dia às 08:00 eu te lembro: remédio\nO primeiro é amanhã.",
        ),
    ],
)
def test_confirmacao(palavras, esperado):
    assert confirmar(interpretar(palavras, AGORA), AGORA) == esperado


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


@pytest.mark.parametrize(
    ("momento", "esperado"),
    [
        (datetime(2026, 9, 27, 8, 0, tzinfo=FUSO), "hoje às 08:00"),
        (datetime(2026, 9, 24, 8, 0, tzinfo=FUSO), "24/09 às 08:00"),
        (datetime(2025, 12, 31, 23, 0, tzinfo=FUSO), "31/12/2025 às 23:00"),
    ],
)
def test_data_e_hora(momento, esperado):
    assert data_e_hora(momento, AGORA) == esperado


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

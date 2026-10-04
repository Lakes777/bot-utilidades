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
    ler_data,
    ler_dia_da_semana,
    ler_horario,
    ler_numero,
    ler_tempo,
    proxima_vez,
    proxima_vez_no_dia,
    toda_semana,
)

AGORA = datetime(2026, 9, 27, 10, 0, tzinfo=FUSO)  # um domingo


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
    ("texto", "esperado"),
    [
        ("25/12", datetime(2026, 12, 25, 9, 0, tzinfo=FUSO)),
        ("5/1", datetime(2027, 1, 5, 9, 0, tzinfo=FUSO)),  # já passou este ano: o próximo
        ("28/09", datetime(2026, 9, 28, 9, 0, tzinfo=FUSO)),
        ("25/12/2027", datetime(2027, 12, 25, 9, 0, tzinfo=FUSO)),
        ("25/12/27", datetime(2027, 12, 25, 9, 0, tzinfo=FUSO)),
        ("29/02", datetime(2028, 2, 29, 9, 0, tzinfo=FUSO)),  # próximo ano bissexto
    ],
)
def test_le_datas(texto, esperado):
    assert ler_data(texto, time(9, 0), AGORA) == esperado


def test_data_de_hoje_com_horario_que_ainda_vem():
    assert ler_data("27/09", time(18, 0), AGORA) == datetime(2026, 9, 27, 18, 0, tzinfo=FUSO)


def test_data_de_hoje_sem_horario_depois_das_9h_explica():
    with pytest.raises(LembreteError, match="Sem horário, o lembrete fica para as 09:00"):
        ler_data("27/09", None, AGORA)


def test_data_sem_horario_usa_9h():
    assert ler_data("25/12", None, AGORA) == datetime(2026, 12, 25, 9, 0, tzinfo=FUSO)


def test_data_de_hoje_com_horario_que_ja_passou_e_engano():
    # Não vira lembrete para daqui a um ano.
    with pytest.raises(LembreteError, match="O horário 08:00 de hoje já passou"):
        ler_data("27/09", time(8, 0), AGORA)


@pytest.mark.parametrize("texto", ["31/02", "31/04", "0/5", "25/13", "29/02/2027"])
def test_recusa_datas_que_nao_existem(texto):
    with pytest.raises(LembreteError, match="não existe"):
        ler_data(texto, time(9, 0), AGORA)


@pytest.mark.parametrize("texto", ["26/09/2026", "25/12/2025", "1/1/26"])
def test_recusa_datas_que_ja_passaram(texto):
    with pytest.raises(LembreteError, match="já passou"):
        ler_data(texto, time(9, 0), AGORA)


def test_data_no_maximo_cinco_anos_a_frente():
    assert ler_data("31/12/2031", time(9, 0), AGORA).year == 2031
    with pytest.raises(LembreteError, match="no máximo 5 anos"):
        ler_data("1/1/2032", time(9, 0), AGORA)


@pytest.mark.parametrize("texto", ["25-12", "25/12/2", "dez/25", "25.12"])
def test_recusa_datas_mal_escritas(texto):
    with pytest.raises(LembreteError, match="Não entendi a data"):
        ler_data(texto, time(9, 0), AGORA)


def test_data_usa_o_dia_de_brasilia():
    # 01:00 em UTC do dia 28 ainda é 22:00 do dia 27 em Brasília: 27/09 23:00 é hoje.
    agora_utc = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)
    assert ler_data("27/09", time(23, 0), agora_utc) == datetime(2026, 9, 27, 23, 0, tzinfo=FUSO)


def test_interpreta_data_com_horario():
    assert interpretar(["25/12", "20:30", "ceia", "na", "vó"], AGORA) == Pedido(
        datetime(2026, 12, 25, 20, 30, tzinfo=FUSO), "ceia na vó"
    )


def test_interpreta_data_sem_horario_usa_9h():
    assert interpretar(["15/10", "aniversário", "do", "Rafa"], AGORA) == Pedido(
        datetime(2026, 10, 15, 9, 0, tzinfo=FUSO), "aniversário do Rafa"
    )


@pytest.mark.parametrize("palavras", [["25/12"], ["25/12", "9:00"], ["25/12", "às", "9:00"]])
def test_data_sem_texto_mostra_como_usar(palavras):
    with pytest.raises(LembreteError, match="Use assim"):
        interpretar(palavras, AGORA)


def test_data_com_horario_que_nao_existe():
    with pytest.raises(LembreteError, match='"25:00" não existe'):
        interpretar(["25/12", "25:00", "ceia"], AGORA)


@pytest.mark.parametrize("inicio", [["às"], ["as"], ["Às"]])
def test_interpreta_data_com_as_antes_do_horario(inicio):
    assert interpretar(["25/12", *inicio, "20:30", "ceia"], AGORA) == Pedido(
        datetime(2026, 12, 25, 20, 30, tzinfo=FUSO), "ceia"
    )


def test_as_sem_horario_valido_e_erro():
    with pytest.raises(LembreteError, match="Não entendi o horário"):
        interpretar(["25/12", "às", "ceia"], AGORA)


@pytest.mark.parametrize("horario", ["20h", "9h30", "20H"])
def test_data_com_horario_sem_dois_pontos_e_erro(horario):
    # Sem o aviso, viraria 9:00 com o texto "20h ceia".
    with pytest.raises(LembreteError, match="dois-pontos"):
        interpretar(["25/12", horario, "ceia"], AGORA)


def test_texto_que_comeca_com_algo_como_data_vira_data():
    # Intencional: "1/2" segue o formato de data e a confirmação mostra o dia.
    assert interpretar(["1/2", "pizza"], AGORA) == Pedido(
        datetime(2027, 2, 1, 9, 0, tzinfo=FUSO), "pizza"
    )


def test_data_na_virada_do_ano_confirma_amanha():
    agora = datetime(2026, 12, 31, 23, 50, tzinfo=FUSO)
    pedido = interpretar(["1/1", "0:10", "abraços"], agora)
    assert pedido.quando == datetime(2027, 1, 1, 0, 10, tzinfo=FUSO)
    assert confirmar(pedido, agora) == "✅ Combinado! Amanhã às 00:10 eu te lembro: abraços"


def test_confirmacao_de_data_usa_o_dia_de_brasilia():
    # 01:00 em UTC do dia 28 ainda é 22:00 do dia 27 em Brasília.
    agora_utc = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)
    pedido = interpretar(["28/09", "8:00", "dentista"], agora_utc)
    assert confirmar(pedido, agora_utc) == "✅ Combinado! Amanhã às 08:00 eu te lembro: dentista"


def test_data_no_meio_do_texto_nao_e_data():
    pedido = interpretar(["10m", "pagar", "até", "25/12"], AGORA)
    assert pedido.texto == "pagar até 25/12"


@pytest.mark.parametrize(
    ("palavra", "esperado"),
    [
        ("segunda", 0), ("Terça", 1), ("terca", 1), ("quarta-feira", 2), ("QUINTA", 3),
        ("Quinta-Feira", 3), ("sexta", 4), ("sábado", 5), ("sabado", 5), ("domingo", 6),
        ("seg", 0), ("qui", 3), ("sáb", 5), ("dom", 6),
        ("quintas", 3), ("sábados", 5), ("quintas-feiras", 3), ("domingos", 6),
    ],
)
def test_le_dias_da_semana(palavra, esperado):
    assert ler_dia_da_semana(palavra) == esperado


@pytest.mark.parametrize("palavra", ["dia", "dias", "semana", "feira", "s", "8:00", ""])
def test_o_que_nao_e_dia_da_semana(palavra):
    assert ler_dia_da_semana(palavra) is None


@pytest.mark.parametrize(
    ("dias", "esperado"),
    [
        ((0,), "toda segunda"),
        ((3,), "toda quinta"),
        ((5,), "todo sábado"),
        ((6,), "todo domingo"),
        ((0, 2), "toda segunda e quarta"),
        ((0, 2, 4), "toda segunda, quarta e sexta"),
        ((5, 6), "todo fim de semana"),
        ((0, 1, 2, 3, 4), "todo dia útil"),
        (tuple(range(7)), "todo dia"),
    ],
)
def test_toda_semana(dias, esperado):
    assert toda_semana(dias) == esperado


@pytest.mark.parametrize(
    ("dia", "horario", "esperado"),
    [
        (3, time(19, 0), datetime(2026, 10, 1, 19, 0, tzinfo=FUSO)),  # quinta que vem
        (0, time(8, 0), datetime(2026, 9, 28, 8, 0, tzinfo=FUSO)),  # amanhã é segunda
        (6, time(18, 0), datetime(2026, 9, 27, 18, 0, tzinfo=FUSO)),  # hoje, mais tarde
        (6, time(8, 0), datetime(2026, 10, 4, 8, 0, tzinfo=FUSO)),  # hoje, mas já passou
        (6, time(10, 0), datetime(2026, 10, 4, 10, 0, tzinfo=FUSO)),  # é agora: semana que vem
        (5, time(9, 0), datetime(2026, 10, 3, 9, 0, tzinfo=FUSO)),  # ontem foi sábado
    ],
)
def test_proxima_vez_no_dia(dia, horario, esperado):
    assert proxima_vez_no_dia(dia, horario, AGORA) == esperado


def test_proxima_vez_no_dia_usa_o_relogio_de_brasilia():
    # 01:00 em UTC de segunda (28) ainda é 22:00 de domingo (27) em Brasília.
    agora_utc = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)
    assert proxima_vez_no_dia(6, time(23, 0), agora_utc) == datetime(2026, 9, 27, 23, 0, tzinfo=FUSO)


@pytest.mark.parametrize(
    "inicio",
    [
        ["toda", "quinta"],
        ["Toda", "Quinta-feira"],
        ["toda", "quinta", "feira"],
        ["toda", "quinta", "às"],
        ["toda", "qui", "as"],
        ["todo", "quinta"],
        ["todas", "as", "quintas"],
        ["Todas", "as", "quintas-feiras", "às"],
        ["toda", "quintas", "feiras"],
    ],
)
def test_interpreta_lembrete_semanal(inicio):
    assert interpretar([*inicio, "19:00", "futebol"], AGORA) == Pedido(
        datetime(2026, 10, 1, 19, 0, tzinfo=FUSO), "futebol", semanal=True, dias=(3,)
    )


def test_todo_sabado():
    pedido = interpretar(["todo", "sábado", "9:30", "feira", "livre"], AGORA)
    assert pedido == Pedido(datetime(2026, 10, 3, 9, 30, tzinfo=FUSO), "feira livre", semanal=True, dias=(5,))


def test_todos_os_sabados():
    pedido = interpretar(["todos", "os", "sábados", "9:30", "feira"], AGORA)
    assert pedido == Pedido(datetime(2026, 10, 3, 9, 30, tzinfo=FUSO), "feira", semanal=True, dias=(5,))


def test_semanal_na_virada_do_ano_mostra_o_ano():
    agora = datetime(2026, 12, 29, 10, 0, tzinfo=FUSO)  # uma terça
    pedido = interpretar(["toda", "sexta", "18:00", "pizza"], agora)
    assert confirmar(pedido, agora) == (
        "✅ Combinado! Toda sexta às 18:00 eu te lembro: pizza\nO primeiro é em 01/01/2027."
    )


@pytest.mark.parametrize(
    ("palavras", "dias", "primeiro"),
    [
        (["toda", "seg", "e", "qua", "7:00"], (0, 2), datetime(2026, 9, 28, 7, 0, tzinfo=FUSO)),
        (["toda", "segunda,", "quarta", "e", "sexta", "7:00"], (0, 2, 4), datetime(2026, 9, 28, 7, 0, tzinfo=FUSO)),
        (["toda", "seg,", "qua,", "sex", "7:00"], (0, 2, 4), datetime(2026, 9, 28, 7, 0, tzinfo=FUSO)),
        (["todas", "as", "terças", "e", "quintas", "às", "7:00"], (1, 3), datetime(2026, 9, 29, 7, 0, tzinfo=FUSO)),
        (["toda", "quarta", "feira", "e", "sexta", "feira", "7:00"], (2, 4), datetime(2026, 9, 30, 7, 0, tzinfo=FUSO)),
        (["toda", "seg", "a", "sex", "7:00"], (0, 1, 2, 3, 4), datetime(2026, 9, 28, 7, 0, tzinfo=FUSO)),
        (["toda", "sex", "a", "seg", "7:00"], (0, 4, 5, 6), datetime(2026, 9, 28, 7, 0, tzinfo=FUSO)),
        (["dias", "úteis", "7:00"], (0, 1, 2, 3, 4), datetime(2026, 9, 28, 7, 0, tzinfo=FUSO)),
        (["todo", "dia", "útil", "7:00"], (0, 1, 2, 3, 4), datetime(2026, 9, 28, 7, 0, tzinfo=FUSO)),
        (["todos", "os", "dias", "uteis", "7:00"], (0, 1, 2, 3, 4), datetime(2026, 9, 28, 7, 0, tzinfo=FUSO)),
        (["fim", "de", "semana", "11:00"], (5, 6), datetime(2026, 9, 27, 11, 0, tzinfo=FUSO)),
        (["todo", "fim", "de", "semana", "9:00"], (5, 6), datetime(2026, 10, 3, 9, 0, tzinfo=FUSO)),
        (["toda", "qua", "e", "qua", "7:00"], (2,), datetime(2026, 9, 30, 7, 0, tzinfo=FUSO)),
        (["toda", "seg", "a", "seg", "7:00"], tuple(range(7)), datetime(2026, 9, 28, 7, 0, tzinfo=FUSO)),
        (["toda", "segunda,quarta", "7:00"], (0, 2), datetime(2026, 9, 28, 7, 0, tzinfo=FUSO)),
        (["toda", "seg,qua,", "sex", "7:00"], (0, 2, 4), datetime(2026, 9, 28, 7, 0, tzinfo=FUSO)),
    ],
)
def test_varios_dias(palavras, dias, primeiro):
    pedido = interpretar([*palavras, "academia"], AGORA)
    assert pedido == Pedido(primeiro, "academia", semanal=True, dias=dias)


def test_dia_sem_toda_e_so_uma_vez():
    # "quinta 19:00 dentista": a próxima quinta, sem repetir.
    assert interpretar(["quinta", "19:00", "dentista"], AGORA) == Pedido(
        datetime(2026, 10, 1, 19, 0, tzinfo=FUSO), "dentista"
    )


def test_varios_dias_sem_toda_pede_o_toda():
    with pytest.raises(LembreteError, match='comece com "toda": /lembrar toda segunda e quarta'):
        interpretar(["seg", "e", "qua", "7:00", "academia"], AGORA)


def test_texto_com_virgula_e_dia_da_semana_fica_inteiro():
    pedido = interpretar(["toda", "sexta", "18:00", "pizza,", "sábado", "e", "domingo"], AGORA)
    assert pedido.dias == (4,)
    assert pedido.texto == "pizza, sábado e domingo"


def test_virgula_sem_espaco_no_texto_fica_inteira():
    pedido = interpretar(["toda", "sexta", "18:00", "pão,leite,sex"], AGORA)
    assert pedido.texto == "pão,leite,sex"


@pytest.mark.parametrize(
    ("palavras", "exemplo"),
    [
        (["toda", "seg", "e", "7:00", "x"], "/lembrar toda segunda 7:00 ..."),
        (["domingo", "pagar", "conta"], "/lembrar domingo 7:00 ..."),
    ],
)
def test_sem_horario_depois_dos_dias_explica(palavras, exemplo):
    with pytest.raises(LembreteError, match="Depois dos dias vem o horário") as erro:
        interpretar(palavras, AGORA)
    assert exemplo in str(erro.value)


def test_e_seguido_de_algo_que_nao_e_dia_vira_horario_errado():
    with pytest.raises(LembreteError, match="Não entendi o horário"):
        interpretar(["toda", "seg", "e", "sempre", "7:00", "x"], AGORA)


def test_todo_dia_continua_diario():
    pedido = interpretar(["todo", "dia", "8:00", "remédio"], AGORA)
    assert pedido.diario and not pedido.semanal


@pytest.mark.parametrize(
    ("palavras", "esperado"),
    [
        (["toda", "seg", "e", "qua", "7:00", "academia"],
         "✅ Combinado! Toda segunda e quarta às 07:00 eu te lembro: academia\nO primeiro é amanhã."),
        (["dias", "úteis", "7:00", "acordar"],
         "✅ Combinado! Todo dia útil às 07:00 eu te lembro: acordar\nO primeiro é amanhã."),
        (["quinta", "19:00", "dentista"],
         "✅ Combinado! Em 01/10 às 19:00 eu te lembro: dentista"),
    ],
)
def test_confirmacao_de_varios_dias(palavras, esperado):
    assert confirmar(interpretar(palavras, AGORA), AGORA) == esperado


def test_semanal_precisa_de_horario():
    with pytest.raises(LembreteError, match="Não entendi o horário"):
        interpretar(["toda", "quinta", "futebol", "com", "a", "galera"], AGORA)


@pytest.mark.parametrize(
    "palavras", [["toda", "quinta"], ["toda", "quinta", "19:00"], ["toda", "quinta-feira", "às", "19:00"]]
)
def test_semanal_sem_texto_mostra_como_usar(palavras):
    with pytest.raises(LembreteError, match="Use assim"):
        interpretar(palavras, AGORA)


def test_toda_no_meio_do_texto_nao_e_semanal():
    pedido = interpretar(["10m", "toda", "quinta", "tem", "futebol"], AGORA)
    assert not pedido.semanal
    assert pedido.texto == "toda quinta tem futebol"


def test_toda_sem_dia_da_semana_nao_e_semanal():
    # "toda" seguido de outra coisa cai no caminho normal e dá erro de tempo.
    with pytest.raises(LembreteError, match="Não entendi o tempo"):
        interpretar(["toda", "hora", "beber", "água"], AGORA)


@pytest.mark.parametrize(
    ("palavras", "esperado"),
    [
        (["1h30m", "reunião"], "✅ Combinado! Daqui a 1h30min (às 11:30) eu te lembro: reunião"),
        (["2d", "boleto"], "✅ Combinado! Daqui a 2d (em 29/09 às 10:00) eu te lembro: boleto"),
        (["18:30", "ligar"], "✅ Combinado! Hoje às 18:30 eu te lembro: ligar"),
        (["9:15", "ligar"], "✅ Combinado! Amanhã às 09:15 eu te lembro: ligar"),
        (["27/09", "18:00", "ligar"], "✅ Combinado! Hoje às 18:00 eu te lembro: ligar"),
        (["28/09", "ligar"], "✅ Combinado! Amanhã às 09:00 eu te lembro: ligar"),
        (["25/12", "20:30", "ceia"], "✅ Combinado! Em 25/12 às 20:30 eu te lembro: ceia"),
        (["5/1", "boleto"], "✅ Combinado! Em 05/01/2027 às 09:00 eu te lembro: boleto"),
        (
            ["toda", "quinta", "19:00", "futebol"],
            "✅ Combinado! Toda quinta às 19:00 eu te lembro: futebol\nO primeiro é em 01/10.",
        ),
        (
            ["todo", "domingo", "20:00", "lavar", "roupa"],
            "✅ Combinado! Todo domingo às 20:00 eu te lembro: lavar roupa\nO primeiro é hoje.",
        ),
        (
            ["toda", "segunda", "8:00", "academia"],
            "✅ Combinado! Toda segunda às 08:00 eu te lembro: academia\nO primeiro é amanhã.",
        ),
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

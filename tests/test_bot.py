import asyncio
import logging
from datetime import datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from telegram import Bot, CallbackQuery, Message, Update, User
from telegram.error import BadRequest, Forbidden
from telegram.ext import CallbackQueryHandler, CommandHandler

from bot_utilidades import bot, clima, cotacoes, spendwise
from bot_utilidades.armazenamento import AvisoChuva, Banco
from bot_utilidades.bot import (
    configurar_logs,
    criar_app,
    cancelar,
    conferir_alertas,
    criar_alerta,
    enviar_lembrete,
    lembrar,
    listar_alertas,
    listar_lembretes,
    reagendar,
    remover_alerta,
    responder_botao,
    mudar,
    configurar_chuva,
    conferir_chuva,
    adicionar_na_lista,
    mostrar_lista,
    riscar_da_lista,
    limpar_lista,
    converter_moedas,
    lancar_gasto,
)
from bot_utilidades.alertas import LIMITE_POR_CHAT as LIMITE_ALERTAS
from bot_utilidades.lembretes import FUSO, LIMITE_POR_CHAT

TOKEN_FALSO = "123456789:" + "A" * 35
AGORA = datetime(2026, 9, 27, 10, 0, tzinfo=FUSO)


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "lembretes.db")


@pytest.fixture(autouse=True)
def relogio_parado(monkeypatch):
    """O bot pensa que agora é sempre 27/09/2026 às 10:00 em Brasília."""
    monkeypatch.setattr(bot, "agora", lambda: AGORA)


def comandos_registrados(app) -> set[str]:
    return {
        comando
        for handler in app.handlers[0]
        if isinstance(handler, CommandHandler)
        for comando in handler.commands
    }


def test_lembrar_numa_data(banco):
    _, respostas = simular_lembrar(["25/12", "20:30", "ceia", "na", "vó"], banco)

    [lembrete] = banco.todos()
    assert lembrete.quando == datetime(2026, 12, 25, 20, 30, tzinfo=FUSO)
    assert not lembrete.diario
    assert respostas == ["✅ Combinado! Em 25/12 às 20:30 eu te lembro: ceia na vó"]


def test_lembrar_horario_fixo_e_diario(banco):
    _, respostas = simular_lembrar(["18:30", "ligar", "pra", "mãe"], banco)
    _, respostas_diario = simular_lembrar(["todo", "dia", "8:00", "remédio"], banco)

    fixo, diario = banco.todos()
    assert fixo.quando == datetime(2026, 9, 27, 18, 30, tzinfo=FUSO)
    assert not fixo.diario
    assert diario.quando == datetime(2026, 9, 28, 8, 0, tzinfo=FUSO)
    assert diario.diario
    assert respostas == ["✅ Combinado! Hoje às 18:30 eu te lembro: ligar pra mãe"]
    assert respostas_diario[0].startswith("✅ Combinado! Todo dia às 08:00")


def test_registra_todos_os_comandos(banco):
    # Montar o app não conecta ao Telegram, então o token falso basta.
    esperados = {
        "start", "ajuda", "bitcoin", "dolar", "clima", "lembrar", "lembretes", "cancelar",
        "alerta", "alertas", "removeralerta", "mudar", "chuva", "add", "lista", "feito", "limpar", "converter", "gasto",
    }
    assert esperados <= comandos_registrados(criar_app(TOKEN_FALSO, banco))


def test_logs_nao_mostram_o_token():
    # O httpx loga a URL de cada requisição, e a URL da API do Telegram contém o token.
    configurar_logs()
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)


class Falso:
    """Imita os objetos do Telegram guardando o que o bot tentou fazer."""

    def __init__(self):
        self.chamadas = []

    def gravar(self, nome):
        async def metodo(*args, **kwargs):
            self.chamadas.append((nome, args, kwargs))
        return metodo


def simular_lembrar(args, banco, chat_id=42):
    falso = Falso()
    agendados = []
    update = SimpleNamespace(
        message=SimpleNamespace(reply_text=falso.gravar("reply_text")),
        effective_chat=SimpleNamespace(id=chat_id),
    )
    context = SimpleNamespace(
        args=args,
        bot_data={"banco": banco},
        job_queue=SimpleNamespace(run_once=lambda *a, **kw: agendados.append((a, kw))),
    )
    asyncio.run(lembrar(update, context))
    respostas = [args[0] for nome, args, _ in falso.chamadas if nome == "reply_text"]
    return agendados, respostas


def test_lembrar_salva_agenda_e_confirma(banco):
    agendados, respostas = simular_lembrar(["1h30m", "tomar", "água"], banco)

    [lembrete] = banco.todos()
    assert lembrete.chat_id == 42
    assert lembrete.texto == "tomar água"
    assert lembrete.quando == AGORA + timedelta(hours=1, minutes=30)

    [(args, kwargs)] = agendados
    assert args == (enviar_lembrete,)
    assert kwargs["when"] == lembrete.quando
    assert kwargs["chat_id"] == 42
    assert kwargs["data"] == lembrete.id
    assert kwargs["job_kwargs"] == {"misfire_grace_time": None}
    assert respostas == ["✅ Combinado! Daqui a 1h30min (às 11:30) eu te lembro: tomar água"]


def test_lembrar_outro_dia_mostra_a_data(banco):
    _, respostas = simular_lembrar(["1d", "pagar", "boleto"], banco)
    assert "(em 28/09 às 10:00)" in respostas[0]


def test_lembrar_com_erro_nao_salva_nem_agenda(banco):
    agendados, respostas = simular_lembrar(["dez", "minutos"], banco)
    assert agendados == []
    assert banco.todos() == []
    assert respostas[0].startswith("⚠️ Não entendi")


def test_limite_de_lembretes_por_chat(banco):
    for _ in range(LIMITE_POR_CHAT):
        banco.adicionar(42, "x", AGORA)
    banco.adicionar(7, "de outra pessoa", AGORA)

    agendados, respostas = simular_lembrar(["10m", "mais", "um"], banco)
    assert agendados == []
    assert banco.contar(42) == LIMITE_POR_CHAT
    assert respostas[0].startswith(f"⚠️ Você já tem {LIMITE_POR_CHAT} lembretes")

    # O limite é por chat: outra pessoa continua podendo criar.
    agendados, _ = simular_lembrar(["10m", "mais", "um"], banco, chat_id=8)
    assert len(agendados) == 1


def simular_envio(banco, lembrete_id, erro=None, agendados=None, durante_envio=None):
    falso = Falso()
    enviar = falso.gravar("send_message")
    agendados = [] if agendados is None else agendados

    async def send_message(*args, **kwargs):
        await enviar(*args, **kwargs)
        if durante_envio:
            durante_envio()  # imita outro comando chegando enquanto a mensagem vai
        if erro:
            raise erro

    context = SimpleNamespace(
        job=SimpleNamespace(data=lembrete_id),
        bot=SimpleNamespace(send_message=send_message),
        bot_data={"banco": banco},
        job_queue=SimpleNamespace(run_once=lambda *a, **kw: agendados.append(kw)),
    )
    asyncio.run(enviar_lembrete(context))
    return falso.chamadas


def test_enviar_lembrete_manda_para_o_chat_certo_e_apaga(banco):
    lembrete = banco.adicionar(42, "tomar água", AGORA)
    [(nome, args, kwargs)] = simular_envio(banco, lembrete.id)
    assert (nome, args) == ("send_message", (42, "⏰ Lembrete: tomar água"))
    assert banco.todos() == []
    botoes = kwargs["reply_markup"].inline_keyboard[0]
    assert [(b.text, b.callback_data) for b in botoes] == [
        ("Adiar 10 min", "adiar10:1"), ("Adiar 1 h", "adiar60:1"), ("Feito", "feito:1")
    ]


def test_lembrete_atrasado_avisa_o_horario_original(banco):
    lembrete = banco.adicionar(42, "tomar água", AGORA - timedelta(hours=2))
    [(_, (_, mensagem), _)] = simular_envio(banco, lembrete.id)
    assert mensagem == "⏰ Lembrete atrasado (era para hoje às 08:00): tomar água"


def test_lembrete_cancelado_nao_e_enviado(banco):
    lembrete = banco.adicionar(42, "tomar água", AGORA)
    banco.remover(lembrete.id)
    assert simular_envio(banco, lembrete.id) == []


def test_falha_no_envio_mantem_o_lembrete(banco):
    # Sem internet, o lembrete fica no banco e sai quando o bot reiniciar.
    lembrete = banco.adicionar(42, "tomar água", AGORA)
    with pytest.raises(OSError):
        simular_envio(banco, lembrete.id, erro=OSError("sem rede"))
    assert banco.buscar(lembrete.id) == lembrete


def test_quem_bloqueou_o_bot_perde_o_lembrete(banco):
    lembrete = banco.adicionar(42, "tomar água", AGORA)
    simular_envio(banco, lembrete.id, erro=Forbidden("bot was blocked by the user"))
    assert banco.todos() == []


def test_reagenda_os_lembretes_salvos(banco):
    antigo = banco.adicionar(42, "vencido com o bot desligado", AGORA - timedelta(days=1))
    futuro = banco.adicionar(7, "amanhã", AGORA + timedelta(days=1))
    app = criar_app(TOKEN_FALSO, banco)

    reagendar(app)

    jobs = {job.name: job for job in app.job_queue.jobs()}
    assert set(jobs) == {f"lembrete-{antigo.id}", f"lembrete-{futuro.id}"}
    assert jobs[f"lembrete-{futuro.id}"].chat_id == 7
    assert jobs[f"lembrete-{futuro.id}"].job.trigger.run_date == futuro.quando
    # Sem isso, o lembrete vencido seria descartado em silêncio pelo agendador.
    assert jobs[f"lembrete-{antigo.id}"].job.misfire_grace_time is None


def simular_comando(funcao, args, banco, chat_id=42, jobs=()):
    """Roda um comando com Update/Context falsos e devolve as respostas."""
    falso = Falso()
    update = SimpleNamespace(
        message=SimpleNamespace(reply_text=falso.gravar("reply_text")),
        effective_chat=SimpleNamespace(id=chat_id),
    )
    context = SimpleNamespace(
        args=args,
        bot_data={"banco": banco},
        job_queue=SimpleNamespace(
            get_jobs_by_name=lambda nome: [job for job in jobs if job.name == nome]
        ),
    )
    asyncio.run(funcao(update, context))
    return [args[0] for nome, args, _ in falso.chamadas if nome == "reply_text"]


def test_lista_so_os_lembretes_do_chat(banco):
    banco.adicionar(42, "pagar boleto", AGORA + timedelta(days=1))
    banco.adicionar(7, "de outra pessoa", AGORA)
    banco.adicionar(42, "tomar água " + "a" * 100, AGORA + timedelta(minutes=10))

    [resposta] = simular_comando(listar_lembretes, [], banco)
    assert resposta == (
        "Seus lembretes:\n"
        "#3 às 10:10: tomar água aaaaaaaaaaaaaaaaaaaaaaaaaaaa…\n"
        "#1 em 28/09 às 10:00: pagar boleto\n"
        "\nPara cancelar: /cancelar número"
    )


def test_lista_vazia_ensina_a_criar(banco):
    [resposta] = simular_comando(listar_lembretes, [], banco)
    assert resposta.startswith("Você não tem lembretes pendentes")


def test_lista_cheia_cabe_numa_mensagem(banco):
    for _ in range(LIMITE_POR_CHAT):
        banco.adicionar(42, "x" * 500, AGORA + timedelta(days=300))
    [resposta] = simular_comando(listar_lembretes, [], banco)
    assert len(resposta) <= 4096  # limite de uma mensagem do Telegram


class JobFalso:
    def __init__(self, name):
        self.name = name
        self.removido = False

    def schedule_removal(self):
        self.removido = True


def test_cancelar_apaga_e_tira_do_agendador(banco):
    lembrete = banco.adicionar(42, "pagar boleto", AGORA)
    job, outro = JobFalso(f"lembrete-{lembrete.id}"), JobFalso("lembrete-99")

    [resposta] = simular_comando(cancelar, ["#1"], banco, jobs=[job, outro])

    assert resposta == "🗑️ Lembrete #1 cancelado: pagar boleto"
    assert banco.todos() == []
    assert job.removido and not outro.removido


def test_nao_cancela_lembrete_de_outro_chat(banco):
    lembrete = banco.adicionar(7, "de outra pessoa", AGORA)
    job = JobFalso(f"lembrete-{lembrete.id}")

    [resposta] = simular_comando(cancelar, ["1"], banco, chat_id=42, jobs=[job])

    assert resposta == "⚠️ Não achei o lembrete #1. Veja os seus em /lembretes"
    assert banco.buscar(lembrete.id) == lembrete
    assert not job.removido


def test_cancelar_sem_numero_mostra_como_usar(banco):
    [resposta] = simular_comando(cancelar, [], banco)
    assert resposta.startswith("⚠️ Use assim: /cancelar 3")


def test_lembrete_diario_e_reagendado_para_amanha(banco):
    lembrete = banco.adicionar(42, "remédio", AGORA, diario=True)
    agendados = []

    [(_, (_, mensagem), _)] = simular_envio(banco, lembrete.id, agendados=agendados)

    assert mensagem == "⏰ Lembrete: remédio\n(todo dia; para parar: /cancelar 1)"
    [amanha] = banco.todos()
    assert amanha.quando == AGORA + timedelta(days=1)
    [kwargs] = agendados
    assert kwargs["when"] == amanha.quando
    assert kwargs["data"] == lembrete.id


def test_diario_atrasado_sai_uma_vez_so(banco):
    # O bot ficou 3 dias desligado: manda uma mensagem só e marca para a próxima vez.
    tres_dias_atras = datetime(2026, 9, 24, 8, 0, tzinfo=FUSO)
    lembrete = banco.adicionar(42, "remédio", tres_dias_atras, diario=True)

    [(_, (_, mensagem), _)] = simular_envio(banco, lembrete.id)

    assert mensagem.startswith("⏰ Lembrete atrasado (era para 24/09 às 08:00): remédio")
    assert banco.buscar(lembrete.id).quando == datetime(2026, 9, 28, 8, 0, tzinfo=FUSO)


def test_diario_nao_avanca_se_o_envio_falhar(banco):
    lembrete = banco.adicionar(42, "remédio", AGORA, diario=True)
    with pytest.raises(OSError):
        simular_envio(banco, lembrete.id, erro=OSError("sem rede"))
    assert banco.buscar(lembrete.id) == lembrete


def test_diario_de_quem_bloqueou_o_bot_e_apagado(banco):
    lembrete = banco.adicionar(42, "remédio", AGORA, diario=True)
    agendados = []
    simular_envio(banco, lembrete.id, erro=Forbidden("blocked"), agendados=agendados)
    assert banco.todos() == []
    assert agendados == []


def test_lista_mostra_os_diarios(banco):
    banco.adicionar(42, "remédio", datetime(2026, 9, 28, 8, 0, tzinfo=FUSO), diario=True)
    [resposta] = simular_comando(listar_lembretes, [], banco)
    assert "#1 todo dia às 08:00: remédio" in resposta


def test_lembrar_toda_quinta(banco):
    _, respostas = simular_lembrar(["toda", "quinta", "19:00", "futebol"], banco)

    [lembrete] = banco.todos()
    assert lembrete.quando == datetime(2026, 10, 1, 19, 0, tzinfo=FUSO)
    assert lembrete.semanal and not lembrete.diario
    assert respostas[0].startswith("✅ Combinado! Toda quinta às 19:00 eu te lembro: futebol")


def test_lembrar_toda_quinta_feira_as(banco):
    _, respostas = simular_lembrar(["toda", "quinta", "feira", "às", "19:00", "futebol"], banco)

    [lembrete] = banco.todos()
    assert lembrete.quando == datetime(2026, 10, 1, 19, 0, tzinfo=FUSO)
    assert lembrete.semanal and lembrete.texto == "futebol"
    assert respostas == [
        "✅ Combinado! Toda quinta às 19:00 eu te lembro: futebol\nO primeiro é em 01/10."
    ]


def test_lembrete_semanal_e_reagendado_para_a_semana_que_vem(banco):
    lembrete = banco.adicionar(42, "lavar roupa", AGORA, semanal=True)  # domingo 10:00
    agendados = []

    [(_, (_, mensagem), _)] = simular_envio(banco, lembrete.id, agendados=agendados)

    assert mensagem == "⏰ Lembrete: lavar roupa\n(todo domingo; para parar: /cancelar 1)"
    [proximo] = banco.todos()
    assert proximo.quando == AGORA + timedelta(days=7)
    assert proximo.semanal
    [kwargs] = agendados
    assert kwargs["when"] == proximo.quando


def test_semanal_atrasado_sai_uma_vez_so(banco):
    # Era quinta (24/09) às 19:00 e o bot ficou desligado até domingo: sai uma vez
    # e a próxima é a quinta que vem, não a que já passou.
    lembrete = banco.adicionar(42, "futebol", datetime(2026, 9, 24, 19, 0, tzinfo=FUSO), semanal=True)

    [(_, (_, mensagem), _)] = simular_envio(banco, lembrete.id)

    assert mensagem.startswith("⏰ Lembrete atrasado (era para 24/09 às 19:00): futebol")
    assert banco.buscar(lembrete.id).quando == datetime(2026, 10, 1, 19, 0, tzinfo=FUSO)


def test_semanal_nao_avanca_se_o_envio_falhar(banco):
    lembrete = banco.adicionar(42, "futebol", AGORA, semanal=True)
    with pytest.raises(OSError):
        simular_envio(banco, lembrete.id, erro=OSError("sem rede"))
    assert banco.buscar(lembrete.id) == lembrete


def test_lembrar_dias_uteis_e_reagendar_pula_o_fim_de_semana(banco, monkeypatch):
    _, respostas = simular_lembrar(["dias", "úteis", "7:00", "acordar"], banco)
    [lembrete] = banco.todos()
    assert lembrete.dias == (0, 1, 2, 3, 4)
    assert respostas[0].startswith("✅ Combinado! Todo dia útil às 07:00")

    # Sexta 02/10 às 7:00: o próximo é segunda 05/10, não sábado.
    sexta = datetime(2026, 10, 2, 7, 0, tzinfo=FUSO)
    banco.adiar(lembrete.id, sexta)
    monkeypatch.setattr(bot, "agora", lambda: sexta)
    [(_, (_, mensagem), _)] = simular_envio(banco, lembrete.id)
    assert mensagem.endswith("(todo dia útil; para parar: /cancelar 1)")
    assert banco.buscar(lembrete.id).quando == datetime(2026, 10, 5, 7, 0, tzinfo=FUSO)


def test_semanal_de_varios_dias_vai_para_o_proximo_da_lista(banco, monkeypatch):
    segunda = datetime(2026, 9, 28, 19, 0, tzinfo=FUSO)
    lembrete = banco.adicionar(42, "academia", segunda, semanal=True, dias=(0, 2))
    monkeypatch.setattr(bot, "agora", lambda: segunda)
    simular_envio(banco, lembrete.id)
    assert banco.buscar(lembrete.id).quando == datetime(2026, 9, 30, 19, 0, tzinfo=FUSO)


def test_lembrar_todo_dia_10(banco):
    _, respostas = simular_lembrar(["todo", "dia", "10", "9:00", "aluguel"], banco)
    [lembrete] = banco.todos()
    assert lembrete.dia_do_mes == 10
    assert lembrete.quando == datetime(2026, 10, 10, 9, 0, tzinfo=FUSO)
    assert respostas[0].startswith("✅ Combinado! Todo mês, no dia 10, às 09:00")


def test_mensal_e_reagendado_para_o_mes_que_vem(banco, monkeypatch):
    dia_10 = datetime(2026, 10, 10, 9, 0, tzinfo=FUSO)
    lembrete = banco.adicionar(42, "aluguel", dia_10, dia_do_mes=10)
    monkeypatch.setattr(bot, "agora", lambda: dia_10)

    [(_, (_, mensagem), _)] = simular_envio(banco, lembrete.id)

    assert mensagem == "⏰ Lembrete: aluguel\n(todo mês, no dia 10; para parar: /cancelar 1)"
    assert banco.buscar(lembrete.id).quando == datetime(2026, 11, 10, 9, 0, tzinfo=FUSO)


def test_mensal_do_dia_31_volta_ao_31_depois_de_um_mes_curto(banco, monkeypatch):
    # Saiu em 30/09 (setembro não tem 31): o próximo é 31/10, não 30/10.
    trinta = datetime(2026, 9, 30, 9, 0, tzinfo=FUSO)
    lembrete = banco.adicionar(42, "fatura", trinta, dia_do_mes=31)
    monkeypatch.setattr(bot, "agora", lambda: trinta)
    simular_envio(banco, lembrete.id)
    assert banco.buscar(lembrete.id).quando == datetime(2026, 10, 31, 9, 0, tzinfo=FUSO)


def test_mensal_com_o_bot_desligado_por_meses_sai_uma_vez(banco, monkeypatch):
    lembrete = banco.adicionar(42, "aluguel", datetime(2026, 10, 10, 9, 0, tzinfo=FUSO), dia_do_mes=10)
    monkeypatch.setattr(bot, "agora", lambda: datetime(2026, 12, 15, 12, 0, tzinfo=FUSO))

    [(_, (_, mensagem), _)] = simular_envio(banco, lembrete.id)

    assert mensagem.startswith("⏰ Lembrete atrasado (era para 10/10 às 09:00): aluguel")
    assert banco.buscar(lembrete.id).quando == datetime(2027, 1, 10, 9, 0, tzinfo=FUSO)


def test_mensal_do_dia_31_em_fevereiro(banco, monkeypatch):
    janeiro = datetime(2027, 1, 31, 9, 0, tzinfo=FUSO)
    lembrete = banco.adicionar(42, "fatura", janeiro, dia_do_mes=31)
    monkeypatch.setattr(bot, "agora", lambda: janeiro)
    simular_envio(banco, lembrete.id)
    assert banco.buscar(lembrete.id).quando == datetime(2027, 2, 28, 9, 0, tzinfo=FUSO)


def test_lista_mostra_os_mensais(banco):
    banco.adicionar(42, "aluguel", datetime(2026, 10, 10, 9, 0, tzinfo=FUSO), dia_do_mes=10)
    [resposta] = simular_comando(listar_lembretes, [], banco)
    assert "#1 todo mês, no dia 10, às 09:00: aluguel" in resposta


def simular_mudar(args, banco, chat_id=42):
    falso = Falso()
    agendados, removidos = [], []
    job = SimpleNamespace(name="lembrete-1", schedule_removal=lambda: removidos.append("lembrete-1"))
    update = SimpleNamespace(
        message=SimpleNamespace(reply_text=falso.gravar("reply_text")),
        effective_chat=SimpleNamespace(id=chat_id),
    )
    context = SimpleNamespace(
        args=args,
        bot_data={"banco": banco},
        job_queue=SimpleNamespace(
            run_once=lambda *a, **kw: agendados.append(kw),
            get_jobs_by_name=lambda nome: [job] if nome == job.name else [],
        ),
    )
    asyncio.run(mudar(update, context))
    respostas = [args[0] for nome, args, _ in falso.chamadas if nome == "reply_text"]
    return respostas, agendados, removidos


def test_mudar_horario_de_um_diario_mantem_a_repeticao(banco):
    banco.adicionar(42, "remédio", datetime(2026, 9, 28, 8, 0, tzinfo=FUSO), diario=True)

    respostas, agendados, removidos = simular_mudar(["1", "20:00"], banco)

    [lembrete] = banco.todos()
    assert lembrete.diario and lembrete.quando == datetime(2026, 9, 27, 20, 0, tzinfo=FUSO)
    assert respostas == ["✏️ Lembrete #1 agora é todo dia às 20:00: remédio"]
    assert removidos == ["lembrete-1"]
    assert agendados[0]["when"] == lembrete.quando


def test_mudar_horario_de_um_semanal_de_varios_dias(banco):
    banco.adicionar(42, "academia", datetime(2026, 9, 28, 7, 0, tzinfo=FUSO), semanal=True, dias=(0, 2))
    respostas, _, _ = simular_mudar(["1", "19:00"], banco)
    [lembrete] = banco.todos()
    assert lembrete.dias == (0, 2) and lembrete.quando == datetime(2026, 9, 28, 19, 0, tzinfo=FUSO)
    assert respostas == ["✏️ Lembrete #1 agora é toda segunda e quarta às 19:00: academia"]


def test_mudar_horario_de_um_mensal(banco):
    banco.adicionar(42, "aluguel", datetime(2026, 10, 10, 9, 0, tzinfo=FUSO), dia_do_mes=10)
    respostas, _, _ = simular_mudar(["1", "18:00"], banco)
    assert banco.todos()[0].quando == datetime(2026, 10, 10, 18, 0, tzinfo=FUSO)
    assert respostas == ["✏️ Lembrete #1 agora é todo mês, no dia 10, às 18:00: aluguel"]


def test_mudar_horario_de_um_avulso_vai_para_hoje_ou_amanha(banco):
    banco.adicionar(42, "ligar", AGORA + timedelta(days=3))
    respostas, _, _ = simular_mudar(["1", "9:00"], banco)
    [lembrete] = banco.todos()
    assert not lembrete.repete and lembrete.quando == datetime(2026, 9, 28, 9, 0, tzinfo=FUSO)
    assert respostas == ["✏️ Lembrete #1 agora é 28/09 às 09:00: ligar"]


def test_mudar_um_diario_para_uma_data_deixa_de_repetir(banco):
    banco.adicionar(42, "remédio", datetime(2026, 9, 28, 8, 0, tzinfo=FUSO), diario=True)
    respostas, _, _ = simular_mudar(["1", "25/12", "9:00"], banco)
    [lembrete] = banco.todos()
    assert not lembrete.repete and lembrete.quando == datetime(2026, 12, 25, 9, 0, tzinfo=FUSO)
    assert respostas == ["✏️ Lembrete #1 agora é 25/12 às 09:00: remédio"]


def test_mudar_um_avulso_para_toda_sexta(banco):
    banco.adicionar(42, "pizza", AGORA + timedelta(hours=1))
    simular_mudar(["1", "toda", "sexta", "19:00"], banco)
    [lembrete] = banco.todos()
    assert lembrete.semanal and lembrete.dias == (4,)
    assert lembrete.texto == "pizza"


def test_mudar_lembrete_de_outro_chat_nao_funciona(banco):
    original = banco.adicionar(7, "de outra pessoa", AGORA + timedelta(hours=1))
    respostas, agendados, removidos = simular_mudar(["1", "20:00"], banco)
    assert banco.buscar(1) == original
    assert respostas == ["⚠️ Não achei o lembrete #1. Veja os seus em /lembretes"]
    assert agendados == [] and removidos == []


def test_mudar_sem_quando_mostra_como_usar(banco):
    respostas, _, _ = simular_mudar(["1"], banco)
    assert respostas[0].startswith("⚠️ Use assim:\n/mudar 3 20:00")


def test_mudar_durante_o_envio_de_um_diario_vale_a_mudanca(banco):
    lembrete = banco.adicionar(42, "remédio", AGORA, diario=True)
    natal = datetime(2026, 12, 25, 9, 0, tzinfo=FUSO)
    agendados = []

    simular_envio(
        banco, lembrete.id, agendados=agendados,
        durante_envio=lambda: banco.mudar(lembrete.id, 42, natal),
    )

    [mudado] = banco.todos()
    assert mudado.quando == natal and not mudado.diario
    assert agendados == []  # o /mudar já agendou; o envio não agenda de novo


def test_mudar_durante_o_envio_de_um_avulso_nao_apaga(banco):
    lembrete = banco.adicionar(42, "ligar", AGORA)
    depois = AGORA + timedelta(hours=2)
    simular_envio(banco, lembrete.id, durante_envio=lambda: banco.mudar(lembrete.id, 42, depois))
    [mudado] = banco.todos()
    assert mudado.quando == depois


def test_cancelar_durante_o_envio_de_um_diario_nao_quebra(banco):
    lembrete = banco.adicionar(42, "remédio", AGORA, diario=True)
    agendados = []
    simular_envio(
        banco, lembrete.id, agendados=agendados, durante_envio=lambda: banco.cancelar(lembrete.id, 42)
    )
    assert banco.todos() == [] and agendados == []


def test_mudar_para_mensal_sem_horario_avisa(banco):
    banco.adicionar(42, "remédio", datetime(2026, 9, 28, 8, 0, tzinfo=FUSO), diario=True)
    respostas, _, _ = simular_mudar(["1", "todo", "dia", "10"], banco)
    assert respostas == [
        "✏️ Lembrete #1 agora é todo mês, no dia 10, às 09:00: remédio"
        "\nSe queria todo dia às 10h, use /mudar 1 todo dia 10:00"
    ]


def test_mudar_para_uma_data_sem_horario_usa_9h(banco):
    banco.adicionar(42, "ligar", AGORA + timedelta(hours=1))
    simular_mudar(["1", "25/12"], banco)
    assert banco.todos()[0].quando == datetime(2026, 12, 25, 9, 0, tzinfo=FUSO)


def test_mudar_numero_que_nao_existe(banco):
    respostas, _, _ = simular_mudar(["9", "20:00"], banco)
    assert respostas == ["⚠️ Não achei o lembrete #9. Veja os seus em /lembretes"]


def test_lista_mostra_os_semanais(banco):
    banco.adicionar(42, "futebol", datetime(2026, 10, 1, 19, 0, tzinfo=FUSO), semanal=True)
    banco.adicionar(42, "feira", datetime(2026, 10, 3, 9, 30, tzinfo=FUSO), semanal=True)
    [resposta] = simular_comando(listar_lembretes, [], banco)
    assert "#1 toda quinta às 19:00: futebol" in resposta
    assert "#2 todo sábado às 09:30: feira" in resposta
    banco.adicionar(42, "academia", datetime(2026, 9, 28, 7, 0, tzinfo=FUSO), semanal=True, dias=(0, 2))
    [resposta] = simular_comando(listar_lembretes, [], banco)
    assert "#3 toda segunda e quarta às 07:00: academia" in resposta


def simular_botao(dados, banco, chat_id=42, texto="⏰ Lembrete: tomar água", erro_ao_editar=None):
    """Simula o clique num botão; devolve as chamadas feitas e os jobs agendados."""
    falso = Falso()
    agendados = []

    def editar(nome):
        gravar = falso.gravar(nome)

        async def metodo(*args, **kwargs):
            await gravar(*args, **kwargs)
            if erro_ao_editar:
                raise erro_ao_editar
        return metodo

    update = SimpleNamespace(
        callback_query=SimpleNamespace(
            data=dados,
            message=SimpleNamespace(text=texto),
            answer=falso.gravar("answer"),
            edit_message_text=editar("edit_message_text"),
            edit_message_reply_markup=editar("edit_message_reply_markup"),
        ),
        effective_chat=SimpleNamespace(id=chat_id),
    )
    context = SimpleNamespace(
        bot_data={"banco": banco},
        job_queue=SimpleNamespace(run_once=lambda *a, **kw: agendados.append(kw)),
    )
    asyncio.run(responder_botao(update, context))
    return falso.chamadas, agendados


def test_botao_adiar_10_minutos(banco):
    enviado = banco.registrar_envio(42, "tomar água", AGORA)

    chamadas, agendados = simular_botao(f"adiar10:{enviado.id}", banco)

    [novo] = banco.todos()
    assert (novo.chat_id, novo.texto) == (42, "tomar água")
    assert novo.quando == AGORA + timedelta(minutes=10)
    assert agendados[0]["when"] == novo.quando
    assert ("answer", ("Adiado às 10:10",), {}) in chamadas
    assert (
        "edit_message_text", ("⏰ Lembrete: tomar água\n💤 Adiado às 10:10 (#1)",), {}
    ) in chamadas


def test_botao_adiar_1_hora(banco):
    enviado = banco.registrar_envio(42, "reunião", AGORA)
    simular_botao(f"adiar60:{enviado.id}", banco)
    [novo] = banco.todos()
    assert novo.quando == AGORA + timedelta(hours=1)


def test_botao_feito(banco):
    enviado = banco.registrar_envio(42, "tomar água", AGORA)

    chamadas, agendados = simular_botao(f"feito:{enviado.id}", banco)

    assert banco.todos() == [] and agendados == []
    assert ("edit_message_text", ("⏰ Lembrete: tomar água\n✅ Feito",), {}) in chamadas


def test_botao_vale_uma_vez(banco):
    enviado = banco.registrar_envio(42, "tomar água", AGORA)
    simular_botao(f"adiar10:{enviado.id}", banco)

    chamadas, _ = simular_botao(f"adiar10:{enviado.id}", banco)

    assert len(banco.todos()) == 1  # o segundo clique não cria outro
    assert ("answer", ("Esse lembrete já foi respondido ou é antigo demais.",), {}) in chamadas
    assert ("edit_message_reply_markup", (), {"reply_markup": None}) in chamadas


def test_botao_de_outro_chat_nao_funciona(banco):
    enviado = banco.registrar_envio(42, "tomar água", AGORA)
    simular_botao(f"adiar10:{enviado.id}", banco, chat_id=7)
    assert banco.todos() == []
    assert banco.tirar_envio(enviado.id, 42) is not None  # continua valendo para o dono


@pytest.mark.parametrize("dados", ["", "apagar:1", "adiar10:", "adiar10:abc", "feito:-1", None])
def test_botao_com_dados_estranhos_e_ignorado(banco, dados):
    banco.registrar_envio(42, "tomar água", AGORA)
    chamadas, _ = simular_botao(dados, banco)
    assert chamadas == [("answer", (), {})]
    assert banco.todos() == []


def test_botao_adiar_respeita_o_limite(banco):
    for i in range(LIMITE_POR_CHAT):
        banco.adicionar(42, f"lembrete {i}", AGORA + timedelta(days=1))
    enviado = banco.registrar_envio(42, "tomar água", AGORA)

    chamadas, _ = simular_botao(f"adiar10:{enviado.id}", banco)

    assert banco.contar(42) == LIMITE_POR_CHAT
    [(nome, args, kwargs)] = chamadas
    assert nome == "answer" and kwargs == {"show_alert": True}
    # O botão continua valendo depois de cancelar algum lembrete.
    banco.cancelar(1, 42)
    simular_botao(f"adiar10:{enviado.id}", banco)
    assert banco.contar(42) == LIMITE_POR_CHAT


def test_botao_usado_com_limite_cheio_diz_que_ja_foi_respondido(banco):
    for i in range(LIMITE_POR_CHAT):
        banco.adicionar(42, f"lembrete {i}", AGORA + timedelta(days=1))
    chamadas, _ = simular_botao("adiar10:99", banco)
    assert ("answer", ("Esse lembrete já foi respondido ou é antigo demais.",), {}) in chamadas


def test_adiar_um_lembrete_diario_nao_mexe_no_repetido(banco):
    diario = banco.adicionar(42, "remédio", AGORA + timedelta(days=1), diario=True)
    enviado = banco.registrar_envio(42, "remédio", AGORA)
    texto = "⏰ Lembrete: remédio\n(todo dia; para parar: /cancelar 1)"

    chamadas, _ = simular_botao(f"adiar10:{enviado.id}", banco, texto=texto)

    repetido, adiado = sorted(banco.todos(), key=lambda l: l.id)
    assert repetido == diario
    assert not adiado.diario and adiado.quando == AGORA + timedelta(minutes=10)
    assert ("edit_message_text", (texto + "\n💤 Adiado às 10:10 (#2)",), {}) in chamadas


@pytest.mark.parametrize("dados", ["feito:1", "adiar10:1", "adiar10:99"])
def test_edicao_recusada_pelo_telegram_nao_derruba_o_bot(banco, dados):
    banco.registrar_envio(42, "tomar água", AGORA)
    erro = BadRequest("Message is not modified")
    chamadas, _ = simular_botao(dados, banco, erro_ao_editar=erro)
    assert chamadas[0][0] == "answer"


def test_mensagem_inacessivel_so_perde_os_botoes(banco):
    # Mensagem apagada: o Telegram manda um objeto sem texto.
    enviado = banco.registrar_envio(42, "tomar água", AGORA)
    chamadas, _ = simular_botao(f"feito:{enviado.id}", banco, texto=None)
    assert ("edit_message_reply_markup", (), {"reply_markup": None}) in chamadas


def test_envio_que_falha_nao_deixa_registro_para_os_botoes(banco):
    lembrete = banco.adicionar(42, "tomar água", AGORA)
    with pytest.raises(OSError):
        simular_envio(banco, lembrete.id, erro=OSError("sem rede"))
    assert banco.tirar_envio(1, 42) is None


def test_registra_o_handler_dos_botoes(banco):
    app = criar_app(TOKEN_FALSO, banco)
    assert any(isinstance(h, CallbackQueryHandler) for h in app.handlers[0])


def mensagem_de(usuario_id, texto, update_id=1):
    """Monta um Update igual ao que o Telegram manda quando alguém digita um comando."""
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 0,
            "chat": {"id": usuario_id, "type": "private"},
            "from": {"id": usuario_id, "is_bot": False, "first_name": "Teste"},
            "text": texto,
            "entities": [{"type": "bot_command", "offset": 0, "length": len(texto.split()[0])}],
        },
    }


@pytest.fixture
def respostas_do_bot(monkeypatch):
    """Troca o envio de respostas por uma lista, para rodar o app sem internet."""
    respostas = []

    async def reply_text(self, texto, *args, **kwargs):
        respostas.append((self.chat.id, texto))

    async def get_me(self, *args, **kwargs):
        # app.initialize() pergunta ao Telegram quem é o bot; aqui a resposta é inventada
        # e guardada no mesmo lugar em que o get_me de verdade guarda.
        self._bot_user = User(1, "Bot de teste", is_bot=True, username="bot_teste")
        return self._bot_user

    monkeypatch.setattr(Message, "reply_text", reply_text)
    monkeypatch.setattr(Bot, "get_me", get_me)
    return respostas


def processar(app, *updates):
    async def rodar():
        await app.initialize()
        for dados in updates:
            await app.process_update(Update.de_json(dados, app.bot))
        await app.shutdown()

    asyncio.run(rodar())


def test_sem_lista_qualquer_um_usa(banco, respostas_do_bot):
    app = criar_app(TOKEN_FALSO, banco, permitidos=None)
    processar(app, mensagem_de(555, "/ajuda"))
    [(chat, texto)] = respostas_do_bot
    assert chat == 555 and texto.startswith("Comandos disponíveis")


def test_permitido_usa_normalmente(banco, respostas_do_bot):
    app = criar_app(TOKEN_FALSO, banco, permitidos=frozenset({111}))
    processar(app, mensagem_de(111, "/ajuda"))
    [(_, texto)] = respostas_do_bot
    assert texto.startswith("Comandos disponíveis")


def clique_de(usuario_id, dados, update_id=1):
    """Monta um Update igual ao que o Telegram manda quando alguém toca num botão."""
    return {
        "update_id": update_id,
        "callback_query": {
            "id": "clique-1",
            "chat_instance": "1",
            "from": {"id": usuario_id, "is_bot": False, "first_name": "Teste"},
            "data": dados,
            "message": {
                "message_id": 5,
                "date": 0,
                "chat": {"id": usuario_id, "type": "private"},
                "from": {"id": 1, "is_bot": True, "first_name": "Bot"},
                "text": "⏰ Lembrete: tomar água",
            },
        },
    }


def test_clique_de_desconhecido_e_respondido_sem_mensagem_nova(banco, respostas_do_bot, monkeypatch):
    respostas_aos_cliques = []

    async def answer(self, texto=None, *args, **kwargs):
        respostas_aos_cliques.append(texto)

    monkeypatch.setattr(CallbackQuery, "answer", answer)
    enviado = banco.registrar_envio(555, "tomar água", AGORA)
    app = criar_app(TOKEN_FALSO, banco, permitidos=frozenset({111}))

    processar(app, clique_de(555, f"adiar10:{enviado.id}"))

    assert respostas_aos_cliques == ["🔒 Este bot é particular."]
    assert respostas_do_bot == []  # não manda mensagem no chat
    assert banco.todos() == []


def test_desconhecido_e_barrado(banco, respostas_do_bot):
    app = criar_app(TOKEN_FALSO, banco, permitidos=frozenset({111}))
    processar(app, mensagem_de(555, "/lembrar 10m invadir"))

    # Uma resposta só (a do porteiro): o /lembrar nem chegou a rodar.
    assert respostas_do_bot == [
        (
            555,
            "🔒 Este bot é particular.\nSeu ID é 555. Se você conhece o dono, "
            "mande esse número para ele te liberar.",
        )
    ]
    assert banco.todos() == []


def test_meuid_funciona_para_qualquer_um(banco, respostas_do_bot):
    app = criar_app(TOKEN_FALSO, banco, permitidos=frozenset({111}))
    processar(app, mensagem_de(555, "/meuid"), mensagem_de(111, "/meuid", update_id=2))
    assert respostas_do_bot == [
        (555, "Seu ID no Telegram é 555."),
        (111, "Seu ID no Telegram é 111."),
    ]


def test_meuid_ensina_a_fechar_o_bot(banco, respostas_do_bot):
    app = criar_app(TOKEN_FALSO, banco, permitidos=None)
    processar(app, mensagem_de(555, "/meuid"))
    [(_, texto)] = respostas_do_bot
    assert texto.endswith("coloque no .env:\nUSUARIOS_PERMITIDOS=555")



# ---------- Alertas de preço ----------


def cotacao_em(preco, falhar=False):
    """Troca cotacoes.buscar por uma que devolve sempre este preço (ou falha)."""
    consultas = []

    async def buscar(moeda, cliente, chave=None):
        consultas.append(moeda.par)
        if falhar:
            raise cotacoes.CotacaoError("fora do ar")
        return SimpleNamespace(preco=Decimal(preco))

    return buscar, consultas


def simular_alerta(funcao, args, banco, monkeypatch, preco="350000", falhar=False, chat_id=42):
    buscar, _ = cotacao_em(preco, falhar)
    monkeypatch.setattr(cotacoes, "buscar", buscar)
    falso = Falso()
    update = SimpleNamespace(
        message=SimpleNamespace(reply_text=falso.gravar("reply_text")),
        effective_chat=SimpleNamespace(id=chat_id),
    )
    context = SimpleNamespace(args=args, bot_data={"banco": banco, "http": None})
    asyncio.run(funcao(update, context))
    return [args[0] for _, args, _ in falso.chamadas]


def test_criar_alerta_salva_e_mostra_o_preco_atual(banco, monkeypatch):
    respostas = simular_alerta(criar_alerta, ["bitcoin", "acima", "400.000"], banco, monkeypatch)

    [alerta] = banco.todos_alertas()
    assert (alerta.chat_id, alerta.par, alerta.direcao, alerta.valor) == (
        42, "BTC-BRL", "acima", Decimal("400000"),
    )
    assert respostas == [
        f"✅ Alerta #{alerta.id} criado: Bitcoin acima de R$ 400.000,00.\n"
        "Agora está em R$ 350.000,00.\n"
        "Confiro a cada 5 minutos e aviso uma vez só."
    ]


def test_alerta_ja_atingido_nao_e_criado(banco, monkeypatch):
    respostas = simular_alerta(criar_alerta, ["bitcoin", "acima", "300000"], banco, monkeypatch)

    assert banco.todos_alertas() == []
    assert "já está acima desse valor: agora está em R$ 350.000,00" in respostas[0]


def test_alerta_criado_mesmo_sem_cotacao(banco, monkeypatch):
    respostas = simular_alerta(
        criar_alerta, ["dolar", "abaixo", "5,20"], banco, monkeypatch, falhar=True
    )

    assert len(banco.todos_alertas()) == 1
    assert "Agora está" not in respostas[0]


def test_alerta_com_erro_nao_salva(banco, monkeypatch):
    respostas = simular_alerta(criar_alerta, ["euro", "acima", "6"], banco, monkeypatch)

    assert banco.todos_alertas() == []
    assert respostas[0].startswith("⚠️ Não conheço a moeda")


def test_limite_de_alertas_por_chat(banco, monkeypatch):
    for _ in range(LIMITE_ALERTAS):
        banco.adicionar_alerta(42, "BTC-BRL", "acima", Decimal("999999"))

    respostas = simular_alerta(criar_alerta, ["btc", "acima", "500000"], banco, monkeypatch)

    assert len(banco.todos_alertas()) == LIMITE_ALERTAS
    assert "Você já tem 10 alertas" in respostas[0]


def test_listar_e_remover_alertas_so_do_chat(banco, monkeypatch):
    meu = banco.adicionar_alerta(42, "USD-BRL", "abaixo", Decimal("5.2"))
    outro = banco.adicionar_alerta(7, "BTC-BRL", "acima", Decimal("400000"))

    [lista] = simular_alerta(listar_alertas, [], banco, monkeypatch)
    assert f"#{meu.id} Dólar abaixo de R$ 5,2000" in lista and f"#{outro.id}" not in lista

    [resposta] = simular_alerta(remover_alerta, [str(outro.id)], banco, monkeypatch)
    assert resposta.startswith(f"⚠️ Não achei o alerta #{outro.id}")
    [resposta] = simular_alerta(remover_alerta, [f"#{meu.id}"], banco, monkeypatch)
    assert resposta == f"🗑️ Alerta #{meu.id} apagado: Dólar abaixo de R$ 5,2000"
    assert banco.todos_alertas() == [outro]

    [vazia] = simular_alerta(listar_alertas, [], banco, monkeypatch)
    assert vazia.startswith("Você não tem alertas.")
    [sem_numero] = simular_alerta(remover_alerta, [], banco, monkeypatch)
    assert "/removeralerta 2" in sem_numero


def conferir(banco, monkeypatch, preco, erro=None, falhar=False):
    buscar, consultas = cotacao_em(preco, falhar)
    monkeypatch.setattr(cotacoes, "buscar", buscar)
    falso = Falso()
    enviar = falso.gravar("send_message")

    async def send_message(*args, **kwargs):
        if erro:
            raise erro
        await enviar(*args, **kwargs)

    context = SimpleNamespace(
        bot=SimpleNamespace(send_message=send_message), bot_data={"banco": banco, "http": None}
    )
    asyncio.run(conferir_alertas(context))
    return [args for _, args, _ in falso.chamadas], consultas


def test_conferir_avisa_e_apaga_so_os_atingidos(banco, monkeypatch):
    atingido = banco.adicionar_alerta(42, "BTC-BRL", "acima", Decimal("400000"))
    longe = banco.adicionar_alerta(42, "BTC-BRL", "acima", Decimal("500000"))
    de_outro = banco.adicionar_alerta(7, "BTC-BRL", "abaixo", Decimal("450000"))

    enviados, consultas = conferir(banco, monkeypatch, "420000")

    assert consultas == ["BTC-BRL"]  # uma consulta por moeda, não uma por alerta
    assert [chat for chat, _ in enviados] == [42, 7]
    assert enviados[0][1].startswith("🔔 Alerta: Bitcoin acima de R$ 400.000,00")
    assert banco.todos_alertas() == [longe]


def test_conferir_sem_alertas_nem_consulta_a_api(banco, monkeypatch):
    enviados, consultas = conferir(banco, monkeypatch, "420000")
    assert (enviados, consultas) == ([], [])


def test_conferir_sem_cotacao_mantem_os_alertas(banco, monkeypatch):
    banco.adicionar_alerta(42, "BTC-BRL", "acima", Decimal("1"))
    enviados, _ = conferir(banco, monkeypatch, "0", falhar=True)
    assert enviados == [] and len(banco.todos_alertas()) == 1


def test_falha_no_envio_mantem_o_alerta(banco, monkeypatch):
    banco.adicionar_alerta(42, "BTC-BRL", "acima", Decimal("1"))
    conferir(banco, monkeypatch, "420000", erro=TimeoutError("sem internet"))
    assert len(banco.todos_alertas()) == 1


@pytest.mark.parametrize("erro", [Forbidden("bloqueado"), BadRequest("Chat not found")])
def test_chat_bloqueado_ou_apagado_perde_o_alerta(banco, monkeypatch, erro):
    banco.adicionar_alerta(42, "BTC-BRL", "acima", Decimal("1"))
    conferir(banco, monkeypatch, "420000", erro=erro)
    assert banco.todos_alertas() == []


def test_falha_de_rede_devolve_o_alerta_com_o_mesmo_numero(banco, monkeypatch):
    alerta = banco.adicionar_alerta(42, "BTC-BRL", "acima", Decimal("1"))
    conferir(banco, monkeypatch, "420000", erro=TimeoutError("sem internet"))
    assert banco.todos_alertas() == [alerta]


def test_alerta_apagado_durante_a_conferencia_nao_e_enviado(banco, monkeypatch):
    alerta = banco.adicionar_alerta(42, "BTC-BRL", "acima", Decimal("1"))

    async def buscar(moeda, cliente, chave=None):
        banco.cancelar_alerta(alerta.id, 42)  # o usuário manda /removeralerta enquanto isso
        return SimpleNamespace(preco=Decimal("420000"))

    monkeypatch.setattr(cotacoes, "buscar", buscar)
    falso = Falso()
    context = SimpleNamespace(
        bot=SimpleNamespace(send_message=falso.gravar("send_message")),
        bot_data={"banco": banco, "http": None},
    )
    asyncio.run(conferir_alertas(context))
    assert falso.chamadas == []


def test_quem_saiu_da_lista_de_permitidos_nao_recebe_alertas(banco, monkeypatch):
    banco.adicionar_alerta(42, "BTC-BRL", "acima", Decimal("1"))
    estranho = banco.adicionar_alerta(99, "BTC-BRL", "acima", Decimal("1"))
    buscar, _ = cotacao_em("420000")
    monkeypatch.setattr(cotacoes, "buscar", buscar)
    falso = Falso()
    context = SimpleNamespace(
        bot=SimpleNamespace(send_message=falso.gravar("send_message")),
        bot_data={"banco": banco, "http": None, "permitidos": frozenset({42})},
    )
    asyncio.run(conferir_alertas(context))

    assert [args[0] for _, args, _ in falso.chamadas] == [42]
    assert estranho not in banco.todos_alertas()


def test_valor_longe_do_preco_nao_cria_alerta(banco, monkeypatch):
    respostas = simular_alerta(
        criar_alerta, ["dolar", "acima", "5.500"], banco, monkeypatch, preco="5.17"
    )
    assert banco.todos_alertas() == []
    assert respostas[0].startswith("⚠️ Entendi R$ 5.500,0000, mas o Dólar está em R$ 5,1700")


def test_preparar_agenda_a_conferencia_dos_alertas(banco, monkeypatch):
    app = criar_app(TOKEN_FALSO, banco)
    monkeypatch.setattr(type(app.bot), "set_my_commands", lambda self, comandos: asyncio.sleep(0))
    asyncio.run(bot.preparar(app))
    [job] = app.job_queue.get_jobs_by_name("conferir-alertas")
    assert job.callback is conferir_alertas
    asyncio.run(app.bot_data["http"].aclose())


# ---------- Aviso de chuva ----------

CURITIBA = clima.Cidade("Curitiba", "Paraná", "Brasil", -25.4, -49.3)


class JobQueueFalsa:
    """Guarda os run_daily e as remoções, como a JobQueue faria."""

    def __init__(self, nomes_existentes=()):
        self.diarios = []
        self.removidos = []
        self.jobs = [
            SimpleNamespace(name=nome, schedule_removal=lambda nome=nome: self.removidos.append(nome))
            for nome in nomes_existentes
        ]

    def run_daily(self, callback, **kwargs):
        self.diarios.append((callback, kwargs))

    def get_jobs_by_name(self, nome):
        return [job for job in self.jobs if job.name == nome]


def simular_chuva(args, banco, monkeypatch, cidade=CURITIBA, erro=None, jobs=(), buscadas=None):
    async def buscar_cidade(nome, http):
        if buscadas is not None:
            buscadas.append(nome)
        if erro:
            raise erro
        return cidade

    monkeypatch.setattr(clima, "buscar_cidade", buscar_cidade)
    falso = Falso()
    fila = JobQueueFalsa(jobs)
    update = SimpleNamespace(
        message=SimpleNamespace(reply_text=falso.gravar("reply_text")),
        effective_chat=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(args=args, bot_data={"banco": banco, "http": None}, job_queue=fila)
    asyncio.run(configurar_chuva(update, context))
    return [args[0] for _, args, _ in falso.chamadas], fila


def test_chuva_configura_e_agenda(banco, monkeypatch):
    respostas, fila = simular_chuva(["Curitiba", "6:30"], banco, monkeypatch)

    aviso = banco.aviso_chuva(42)
    assert (aviso.cidade, aviso.horario) == ("Curitiba", datetime(2026, 1, 1, 6, 30).time())
    [(callback, kwargs)] = fila.diarios
    assert callback is conferir_chuva
    assert kwargs["time"].hour == 6 and kwargs["time"].minute == 30
    assert kwargs["time"].tzinfo == FUSO
    assert kwargs["name"] == "chuva-42" and kwargs["data"] == 42
    assert respostas == [
        "☔ Combinado! Todo dia às 06:30 eu confiro a previsão de Curitiba, Paraná "
        "e aviso se for chover. Sem chuva, fico quieto.\nPara desligar: /chuva parar"
    ]


def test_chuva_sem_horario_usa_7h_e_cidade_com_espacos(banco, monkeypatch):
    buscadas = []
    simular_chuva(["São", "José", "dos", "Pinhais"], banco, monkeypatch, buscadas=buscadas)
    assert buscadas == ["São José dos Pinhais"]
    assert banco.aviso_chuva(42).horario.hour == 7


def test_chuva_configurar_de_novo_troca_o_agendamento(banco, monkeypatch):
    _, fila = simular_chuva(["Curitiba", "8:00"], banco, monkeypatch, jobs=["chuva-42"])
    assert fila.removidos == ["chuva-42"]
    assert len(fila.diarios) == 1


def test_chuva_cidade_inexistente(banco, monkeypatch):
    erro = clima.ClimaError('Não encontrei a cidade "Xyz". Confira o nome.')
    respostas, fila = simular_chuva(["Xyz"], banco, monkeypatch, erro=erro)
    assert respostas == ['⚠️ Não encontrei a cidade "Xyz". Confira o nome.']
    assert banco.aviso_chuva(42) is None and fila.diarios == []


@pytest.mark.parametrize(("args", "erro"), [(["Curitiba", "25:00"], "não existe"), (["7:00"], "Diga a cidade")])
def test_chuva_com_pedido_errado(banco, monkeypatch, args, erro):
    respostas, _ = simular_chuva(args, banco, monkeypatch)
    assert erro in respostas[0]
    assert banco.aviso_chuva(42) is None


def test_chuva_sem_argumentos_mostra_o_aviso_ou_como_usar(banco, monkeypatch):
    respostas, _ = simular_chuva([], banco, monkeypatch)
    assert respostas[0].startswith("Você não tem aviso de chuva.\nUse assim:")
    simular_chuva(["Curitiba", "7:00"], banco, monkeypatch)
    respostas, _ = simular_chuva([], banco, monkeypatch)
    assert respostas == ["☔ Todo dia às 07:00 eu confiro a previsão de Curitiba, Paraná.\nPara desligar: /chuva parar"]


def test_chuva_parar(banco, monkeypatch):
    simular_chuva(["Curitiba"], banco, monkeypatch)
    respostas, fila = simular_chuva(["Parar"], banco, monkeypatch, jobs=["chuva-42"])
    assert respostas == ["Aviso de chuva desligado."]
    assert banco.aviso_chuva(42) is None and fila.removidos == ["chuva-42"]
    respostas, _ = simular_chuva(["parar"], banco, monkeypatch)
    assert respostas == ["Você não tinha aviso de chuva."]


def rodar_conferencia(banco, monkeypatch, chuva=None, erro=None, erro_no_envio=None, permitidos=None):
    async def buscar_chuva(cidade, http):
        if erro:
            raise erro
        return chuva

    monkeypatch.setattr(clima, "buscar_chuva", buscar_chuva)
    falso = Falso()
    enviar = falso.gravar("send_message")
    removidos = []

    async def send_message(*args, **kwargs):
        await enviar(*args, **kwargs)
        if erro_no_envio:
            raise erro_no_envio

    context = SimpleNamespace(
        job=SimpleNamespace(data=42, schedule_removal=lambda: removidos.append(True)),
        bot=SimpleNamespace(send_message=send_message),
        bot_data={"banco": banco, "http": None, "permitidos": permitidos},
    )
    asyncio.run(conferir_chuva(context))
    return [args for _, args, _ in falso.chamadas], removidos


def salvar_curitiba(banco):
    banco.salvar_aviso_chuva(AvisoChuva(42, "Curitiba", "Paraná", "Brasil", -25.4, -49.3, AGORA.time()))


def test_conferir_chuva_avisa_quando_vai_chover(banco, monkeypatch):
    salvar_curitiba(banco)
    chuva = [(hora, 85 if hora in (15, 16) else 0) for hora in range(24)]
    [(chat, mensagem)], _ = rodar_conferencia(banco, monkeypatch, chuva=chuva)
    assert chat == 42
    assert mensagem.startswith("☔ Vai chover hoje em Curitiba, Paraná: até 85% de chance, das 15h às 17h")


def test_conferir_chuva_fica_quieto_sem_chuva(banco, monkeypatch):
    salvar_curitiba(banco)
    # Choveu às 8h, mas agora são 10h: não interessa mais.
    chuva = [(hora, 90 if hora == 8 else 10) for hora in range(24)]
    envios, _ = rodar_conferencia(banco, monkeypatch, chuva=chuva)
    assert envios == []


def test_conferir_chuva_avisa_quando_a_api_falha(banco, monkeypatch):
    salvar_curitiba(banco)
    envios, _ = rodar_conferencia(banco, monkeypatch, erro=clima.ClimaError("A API de clima está fora do ar."))
    [(_, mensagem)] = envios
    assert mensagem.startswith("⚠️ Não consegui conferir a chuva de hoje em Curitiba, Paraná")


def test_conferir_chuva_desligado_nao_faz_nada(banco, monkeypatch):
    envios, _ = rodar_conferencia(banco, monkeypatch, chuva=[(23, 99)])
    assert envios == []


def test_conferir_chuva_de_quem_bloqueou_o_bot(banco, monkeypatch):
    salvar_curitiba(banco)
    _, removidos = rodar_conferencia(banco, monkeypatch, chuva=[(23, 99)], erro_no_envio=Forbidden("blocked"))
    assert banco.aviso_chuva(42) is None and removidos == [True]


def jobs_de_chuva_ao_iniciar(banco, monkeypatch, horario, conferido_em=None):
    banco.salvar_aviso_chuva(
        AvisoChuva(42, "Curitiba", "Paraná", "Brasil", -25.4, -49.3, horario, conferido_em)
    )
    app = criar_app(TOKEN_FALSO, banco)
    monkeypatch.setattr(type(app.bot), "set_my_commands", lambda self, comandos: asyncio.sleep(0))
    asyncio.run(bot.preparar(app))
    asyncio.run(app.bot_data["http"].aclose())
    return app.job_queue.get_jobs_by_name("chuva-42")


def test_preparar_agenda_os_avisos_de_chuva_no_fuso_de_brasilia(banco, monkeypatch):
    [job] = jobs_de_chuva_ao_iniciar(banco, monkeypatch, time(7, 0))  # agora são 10:00
    assert job.callback is conferir_chuva
    assert str(job.job.trigger.timezone) == "America/Sao_Paulo"
    assert job.job.misfire_grace_time == 7200


def test_reinicio_logo_depois_do_horario_confere_na_hora(banco, monkeypatch):
    # Aviso às 9:00 e o bot voltou às 10:00 sem ter conferido hoje: confere já.
    jobs = jobs_de_chuva_ao_iniciar(banco, monkeypatch, time(9, 0))
    assert len(jobs) == 2  # o diário e o de agora


def test_reinicio_nao_confere_duas_vezes_no_dia(banco, monkeypatch):
    jobs = jobs_de_chuva_ao_iniciar(banco, monkeypatch, time(9, 0), conferido_em=AGORA.date())
    assert len(jobs) == 1


def test_reinicio_muito_depois_do_horario_fica_para_amanha(banco, monkeypatch):
    jobs = jobs_de_chuva_ao_iniciar(banco, monkeypatch, time(7, 59))  # passou de 2 h
    assert len(jobs) == 1


def test_conferir_chuva_marca_o_dia(banco, monkeypatch):
    salvar_curitiba(banco)
    rodar_conferencia(banco, monkeypatch, chuva=[(23, 0)])
    assert banco.aviso_chuva(42).conferido_em == AGORA.date()


def test_conferir_chuva_de_quem_saiu_dos_permitidos(banco, monkeypatch):
    salvar_curitiba(banco)
    envios, removidos = rodar_conferencia(banco, monkeypatch, chuva=[(23, 99)], permitidos=frozenset({7}))
    assert envios == [] and removidos == [True]
    assert banco.aviso_chuva(42) is None


def test_conferir_chuva_de_chat_que_nao_existe_mais(banco, monkeypatch):
    salvar_curitiba(banco)
    _, removidos = rodar_conferencia(
        banco, monkeypatch, chuva=[(23, 99)], erro_no_envio=BadRequest("Chat not found")
    )
    assert banco.aviso_chuva(42) is None and removidos == [True]


@pytest.mark.parametrize("horario", ["7h", "6h30"])
def test_chuva_com_horario_sem_dois_pontos(banco, monkeypatch, horario):
    respostas, _ = simular_chuva(["Curitiba", horario], banco, monkeypatch)
    assert "dois-pontos" in respostas[0]
    assert banco.aviso_chuva(42) is None


# ---------- Lista de compras e tarefas ----------

def simular_lista(funcao, texto, banco, chat_id=42):
    """Roda um comando da lista; texto é a mensagem inteira, como "/add pão, leite"."""
    falso = Falso()
    update = SimpleNamespace(
        message=SimpleNamespace(text=texto, reply_text=falso.gravar("reply_text")),
        effective_chat=SimpleNamespace(id=chat_id),
    )
    context = SimpleNamespace(args=texto.split()[1:], bot_data={"banco": banco})
    asyncio.run(funcao(update, context))
    return [args[0] for _, args, _ in falso.chamadas]


def test_add_e_lista(banco):
    assert simular_lista(adicionar_na_lista, "/add pão, leite", banco) == [
        "📝 Na lista de compras: #1 pão, #2 leite"
    ]
    simular_lista(adicionar_na_lista, "/add tarefas: estudar\nlavar louça", banco)
    [resposta] = simular_lista(mostrar_lista, "/lista", banco)
    assert resposta == (
        "Compras:\n#1 pão\n#2 leite\n\nTarefas:\n#3 estudar\n#4 lavar louça"
        "\n\nQuando terminar: /feito número"
    )
    [so_tarefas] = simular_lista(mostrar_lista, "/lista Tarefas", banco)
    assert "pão" not in so_tarefas and "#3 estudar" in so_tarefas


@pytest.mark.parametrize(
    "texto", ["/add\npão integral\nleite", "/add \npão integral\nleite", "/add\tpão integral\nleite"]
)
def test_add_com_um_item_por_linha(banco, texto):
    simular_lista(adicionar_na_lista, texto, banco)
    assert [i.texto for i in banco.itens_do_chat(42)] == ["pão integral", "leite"]


def test_lista_grande_vai_em_varias_mensagens(banco):
    banco.adicionar_itens(42, "compras", ["a" * 200] * 200)
    respostas = simular_lista(mostrar_lista, "/lista", banco)
    assert len(respostas) > 1 and all(len(r) <= 4096 for r in respostas)


def test_feito_com_numero_gigante(banco):
    [resposta] = simular_lista(riscar_da_lista, "/feito 99999999999999999999", banco)
    assert resposta.startswith("⚠️ Use assim: /feito 2")


def test_add_ignora_mensagem_editada(banco, respostas_do_bot, caplog):
    app = criar_app(TOKEN_FALSO, banco)
    nova = mensagem_de(42, "/add pão")
    editada = {"update_id": 2, "edited_message": {**nova["message"], "edit_date": 1}}
    processar(app, nova, editada)
    assert [i.texto for i in banco.itens_do_chat(42)] == ["pão"]  # não entrou duas vezes
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_add_com_bot_no_nome_do_comando(banco):
    # Em grupos o Telegram manda "/add@nome_do_bot pão".
    simular_lista(adicionar_na_lista, "/add@sidekick_bot pão", banco)
    assert [i.texto for i in banco.itens_do_chat(42)] == ["pão"]


def test_add_vazio(banco):
    [resposta] = simular_lista(adicionar_na_lista, "/add", banco)
    assert resposta.startswith("⚠️ Use assim:")


def test_add_respeita_o_limite(banco):
    banco.adicionar_itens(42, "compras", [f"item {i}" for i in range(199)])
    [resposta] = simular_lista(adicionar_na_lista, "/add a, b", banco)
    assert resposta.startswith("⚠️ A lista aceita até 200 itens")
    assert banco.contar_itens(42) == 199
    simular_lista(adicionar_na_lista, "/add a", banco)
    assert banco.contar_itens(42) == 200


def test_lista_vazia(banco):
    [resposta] = simular_lista(mostrar_lista, "/lista", banco)
    assert resposta.startswith("Sua lista está vazia.")
    [resposta] = simular_lista(mostrar_lista, "/lista tarefas", banco)
    assert resposta.startswith("A lista de tarefas está vazia.")


def test_feito_risca_e_avisa_os_que_nao_achou(banco):
    banco.adicionar_itens(42, "compras", ["pão", "leite"])
    banco.adicionar_itens(7, "compras", ["de outra pessoa"])
    [resposta] = simular_lista(riscar_da_lista, "/feito 1 3 9", banco)
    assert resposta == "✔️ Riscado: pão\n⚠️ Não achei #3, #9. Veja os números em /lista"
    assert [i.texto for i in banco.itens_do_chat(42)] == ["leite"]
    assert banco.contar_itens(7) == 1


def test_feito_sem_numero(banco):
    [resposta] = simular_lista(riscar_da_lista, "/feito pão", banco)
    assert resposta.startswith("⚠️ Use assim: /feito 2")


def test_limpar(banco):
    banco.adicionar_itens(42, "compras", ["pão", "leite"])
    banco.adicionar_itens(42, "tarefas", ["estudar"])
    assert simular_lista(limpar_lista, "/limpar Compras", banco) == ["🗑️ Lista de compras apagada (2 itens)."]
    assert simular_lista(limpar_lista, "/limpar compras", banco) == [
        "⚠️ Não achei a lista de compras. Veja as suas em /lista"
    ]
    assert simular_lista(limpar_lista, "/limpar", banco)[0].startswith("Use assim:")
    assert simular_lista(limpar_lista, "/limpar tudo", banco) == ["🗑️ Todas as listas apagadas (1 item)."]


# ---------- Conversor ----------

def simular_converter(args, monkeypatch, precos=None, falhar=False):
    pedidas = []

    async def buscar(moeda, http, chave=None):
        pedidas.append(moeda.par)
        if falhar:
            raise cotacoes.CotacaoError("A API de cotações está fora do ar. Tente mais tarde.")
        return SimpleNamespace(preco=Decimal(precos[moeda.par]))

    monkeypatch.setattr(cotacoes, "buscar", buscar)
    falso = Falso()
    update = SimpleNamespace(message=SimpleNamespace(reply_text=falso.gravar("reply_text")))
    context = SimpleNamespace(args=args, bot_data={"http": None})
    asyncio.run(converter_moedas(update, context))
    return [args[0] for _, args, _ in falso.chamadas], pedidas


def test_converter_busca_so_as_cotacoes_necessarias(monkeypatch):
    respostas, pedidas = simular_converter(["100", "usd"], monkeypatch, {"USD-BRL": "5.1723"})
    assert respostas == ["💱 US$ 100,00 = R$ 517,23\nCotação: 1 USD = R$ 5,1723"]
    assert pedidas == ["USD-BRL"]


def test_converter_com_api_fora_do_ar(monkeypatch):
    respostas, _ = simular_converter(["100", "usd"], monkeypatch, falhar=True)
    assert respostas == ["⚠️ A API de cotações está fora do ar. Tente mais tarde."]


def test_converter_sem_argumentos_nao_busca_nada(monkeypatch):
    respostas, pedidas = simular_converter([], monkeypatch)
    assert respostas[0].startswith("⚠️ Use assim:\n/converter 100 usd")
    assert pedidas == []


# ---------- Gasto no Spendwise ----------

CONFIG_SPENDWISE = ("https://spendwise.exemplo", "sw_" + "c" * 40)


def simular_gasto(args, monkeypatch, configuracao=CONFIG_SPENDWISE, permitidos=frozenset({42}), erro=None):
    enviados = []

    async def lancar(gasto, url, chave, http):
        enviados.append((gasto, url, chave))
        if erro:
            raise erro
        return 7

    monkeypatch.setattr(spendwise, "lancar", lancar)
    falso = Falso()
    update = SimpleNamespace(message=SimpleNamespace(reply_text=falso.gravar("reply_text")))
    context = SimpleNamespace(
        args=args,
        bot_data={"http": None, "spendwise": configuracao, "permitidos": permitidos},
    )
    asyncio.run(lancar_gasto(update, context))
    return [args[0] for _, args, _ in falso.chamadas], enviados


def test_gasto_lanca_e_confirma(monkeypatch):
    respostas, [(gasto, url, chave)] = simular_gasto(["35,90", "mercado", "pão"], monkeypatch)
    assert (gasto.valor, gasto.categoria, gasto.data) == (Decimal("35.90"), "mercado", AGORA.date())
    assert (url, chave) == CONFIG_SPENDWISE
    assert respostas == ["💸 Lançado no Spendwise: R$ 35,90 em mercado (pão), hoje. (#7)"]


def test_gasto_sem_configuracao(monkeypatch):
    respostas, enviados = simular_gasto(["35", "mercado"], monkeypatch, configuracao=None)
    assert respostas[0].startswith("O /gasto não está configurado")
    assert enviados == []


def test_gasto_com_bot_aberto_e_recusado(monkeypatch):
    respostas, enviados = simular_gasto(["35", "mercado"], monkeypatch, permitidos=None)
    assert "USUARIOS_PERMITIDOS" in respostas[0]
    assert enviados == []


def test_gasto_com_pedido_errado_nao_chama_a_api(monkeypatch):
    respostas, enviados = simular_gasto(["35"], monkeypatch)
    assert respostas[0].startswith("⚠️ Use assim:")
    assert enviados == []


def test_gasto_com_erro_da_api(monkeypatch):
    erro = spendwise.SpendwiseError("Não consegui acessar o Spendwise. Tente mais tarde.")
    respostas, _ = simular_gasto(["35", "mercado"], monkeypatch, erro=erro)
    assert respostas == ["⚠️ Não consegui acessar o Spendwise. Tente mais tarde."]

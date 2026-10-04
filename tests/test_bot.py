import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from telegram import Bot, CallbackQuery, Message, Update, User
from telegram.error import BadRequest, Forbidden
from telegram.ext import CallbackQueryHandler, CommandHandler

from bot_utilidades import bot, cotacoes
from bot_utilidades.armazenamento import Banco
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
        "alerta", "alertas", "removeralerta",
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


def simular_envio(banco, lembrete_id, erro=None, agendados=None):
    falso = Falso()
    enviar = falso.gravar("send_message")
    agendados = [] if agendados is None else agendados

    async def send_message(*args, **kwargs):
        await enviar(*args, **kwargs)
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


def test_lista_mostra_os_semanais(banco):
    banco.adicionar(42, "futebol", datetime(2026, 10, 1, 19, 0, tzinfo=FUSO), semanal=True)
    banco.adicionar(42, "feira", datetime(2026, 10, 3, 9, 30, tzinfo=FUSO), semanal=True)
    [resposta] = simular_comando(listar_lembretes, [], banco)
    assert "#1 toda quinta às 19:00: futebol" in resposta
    assert "#2 todo sábado às 09:30: feira" in resposta


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

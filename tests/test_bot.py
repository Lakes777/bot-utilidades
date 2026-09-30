import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from telegram import Bot, Message, Update, User
from telegram.error import BadRequest, Forbidden

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
    return {comando for handler in app.handlers[0] for comando in handler.commands}


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
    chamadas = simular_envio(banco, lembrete.id)
    assert chamadas == [("send_message", (42, "⏰ Lembrete: tomar água"), {})]
    assert banco.todos() == []


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

    async def buscar(moeda, cliente):
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

    async def buscar(moeda, cliente):
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

import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace

from bot_utilidades.bot import configurar_logs, criar_app, enviar_lembrete, lembrar

TOKEN_FALSO = "123456789:" + "A" * 35


def comandos_registrados(app) -> set[str]:
    return {comando for handler in app.handlers[0] for comando in handler.commands}


def test_registra_todos_os_comandos():
    # Montar o app não conecta ao Telegram, então o token falso basta.
    esperados = {"start", "ajuda", "bitcoin", "dolar", "clima", "lembrar"}
    assert esperados <= comandos_registrados(criar_app(TOKEN_FALSO))


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


def simular_lembrar(args):
    falso = Falso()
    agendados = []
    update = SimpleNamespace(
        message=SimpleNamespace(reply_text=falso.gravar("reply_text")),
        effective_chat=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(
        args=args,
        job_queue=SimpleNamespace(run_once=lambda *a, **kw: agendados.append((a, kw))),
    )
    asyncio.run(lembrar(update, context))
    respostas = [args[0] for nome, args, _ in falso.chamadas if nome == "reply_text"]
    return agendados, respostas


def test_lembrar_agenda_e_confirma():
    agendados, respostas = simular_lembrar(["1h30m", "tomar", "água"])

    [(args, kwargs)] = agendados
    assert args == (enviar_lembrete,)
    assert kwargs["when"] == timedelta(hours=1, minutes=30)
    assert kwargs["chat_id"] == 42
    assert kwargs["data"] == "tomar água"
    assert respostas[0].startswith("✅ Combinado! Daqui a 1h30min")


def test_lembrar_com_erro_nao_agenda():
    agendados, respostas = simular_lembrar(["dez", "minutos"])
    assert agendados == []
    assert respostas[0].startswith("⚠️ Não entendi")


def test_enviar_lembrete_manda_para_o_chat_certo():
    falso = Falso()
    context = SimpleNamespace(
        job=SimpleNamespace(chat_id=42, data="tomar água"),
        bot=SimpleNamespace(send_message=falso.gravar("send_message")),
    )
    asyncio.run(enviar_lembrete(context))
    assert falso.chamadas == [("send_message", (42, "⏰ Lembrete: tomar água"), {})]

"""Monta o bot: liga cada comando do Telegram à função que responde."""

import logging
from datetime import datetime, timedelta

import httpx
from telegram import BotCommand, Update
from telegram.error import Forbidden
from telegram.ext import Application, CommandHandler, ContextTypes, JobQueue

from bot_utilidades import clima, cotacoes, lembretes
from bot_utilidades.armazenamento import Banco, Lembrete

log = logging.getLogger(__name__)

# Um lembrete entregue com mais atraso que isso ganha um aviso (o bot estava desligado).
TOLERANCIA_ATRASO = timedelta(minutes=1)

# Aparecem no menu "/" do Telegram e na mensagem de /ajuda.
COMANDOS = [
    BotCommand("bitcoin", "preço do Bitcoin em reais"),
    BotCommand("dolar", "cotação do dólar"),
    BotCommand("clima", "clima agora, ex.: /clima Curitiba"),
    BotCommand("lembrar", "lembrete, ex.: /lembrar 10m tomar água"),
    BotCommand("ajuda", "lista de comandos"),
]

AJUDA = "Comandos disponíveis:\n" + "\n".join(
    f"/{c.command} - {c.description}" for c in COMANDOS
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    nome = update.effective_user.first_name
    await update.message.reply_text(
        f"Olá, {nome}! Sou um bot de utilidades.\n\n{AJUDA}"
    )


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(AJUDA)


def responder_cotacao(moeda: cotacoes.Moeda):
    """Cria o handler de um comando de cotação (/bitcoin, /dolar...)."""

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        cliente = context.bot_data["http"]
        try:
            texto = cotacoes.formatar(await cotacoes.buscar(moeda, cliente))
        except cotacoes.CotacaoError as erro:
            texto = f"⚠️ {erro}"
        await update.message.reply_text(texto)

    return handler


async def responder_clima(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # context.args são as palavras depois do comando: ["São", "Paulo"]
    nome = " ".join(context.args)
    if not nome:
        await update.message.reply_text("Diga a cidade, ex.: /clima Curitiba")
        return
    try:
        texto = clima.formatar(await clima.buscar(nome, context.bot_data["http"]))
    except clima.ClimaError as erro:
        texto = f"⚠️ {erro}"
    await update.message.reply_text(texto)


def agora() -> datetime:
    """Data e hora atuais em Brasília. Os testes trocam esta função."""
    return datetime.now(lembretes.FUSO)


def agendar(job_queue: JobQueue, lembrete: Lembrete) -> None:
    """Pede ao JobQueue para chamar enviar_lembrete() na hora do lembrete."""
    job_queue.run_once(
        enviar_lembrete,
        when=lembrete.quando,
        chat_id=lembrete.chat_id,
        data=lembrete.id,  # só o número: o texto é lido do banco na hora de enviar
        name=f"lembrete-{lembrete.id}",
        # Por padrão, um job que dispara com mais de 1 s de atraso (PC hibernando,
        # por exemplo) é descartado em silêncio. None = mandar mesmo atrasado.
        # Isso também faz os lembretes vencidos com o bot desligado saírem na hora.
        job_kwargs={"misfire_grace_time": None},
    )


async def lembrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    banco: Banco = context.bot_data["banco"]
    chat_id = update.effective_chat.id
    try:
        tempo, texto = lembretes.interpretar(context.args)
    except lembretes.LembreteError as erro:
        await update.message.reply_text(f"⚠️ {erro}")
        return

    if banco.contar(chat_id) >= lembretes.LIMITE_POR_CHAT:
        await update.message.reply_text(
            f"⚠️ Você já tem {lembretes.LIMITE_POR_CHAT} lembretes pendentes."
        )
        return

    hora = agora()
    lembrete = banco.adicionar(chat_id, texto, hora + tempo)
    agendar(context.job_queue, lembrete)
    await update.message.reply_text(
        f"✅ Combinado! Daqui a {lembretes.descrever(tempo)} "
        f"({lembretes.descrever_horario(lembrete.quando, hora)}) eu te lembro: {texto}"
    )


async def enviar_lembrete(context: ContextTypes.DEFAULT_TYPE) -> None:
    banco: Banco = context.bot_data["banco"]
    lembrete = banco.buscar(context.job.data)
    if lembrete is None:  # foi apagado enquanto esperava
        return

    hora = agora()
    if hora - lembrete.quando > TOLERANCIA_ATRASO:
        horario = lembretes.descrever_horario(lembrete.quando, hora)
        mensagem = f"⏰ Lembrete atrasado (era para {horario}): {lembrete.texto}"
    else:
        mensagem = f"⏰ Lembrete: {lembrete.texto}"

    try:
        await context.bot.send_message(lembrete.chat_id, mensagem)
    except Forbidden:
        # A pessoa bloqueou o bot: não adianta tentar de novo a cada reinício.
        log.warning("Chat %s bloqueou o bot; lembrete %s apagado", lembrete.chat_id, lembrete.id)
    # Só apaga depois de enviar: se a internet cair no envio, o erro sobe,
    # o lembrete continua no banco e sai quando o bot for reiniciado.
    banco.remover(lembrete.id)


async def preparar(app: Application) -> None:
    # Um único cliente HTTP reaproveita conexões entre os comandos.
    app.bot_data["http"] = httpx.AsyncClient()
    await app.bot.set_my_commands(COMANDOS)
    reagendar(app)


def reagendar(app: Application) -> None:
    """Agenda de novo os lembretes salvos (os vencidos saem na hora)."""
    pendentes = app.bot_data["banco"].todos()
    for lembrete in pendentes:
        agendar(app.job_queue, lembrete)
    log.info("%d lembrete(s) reagendado(s)", len(pendentes))


async def fechar_http(app: Application) -> None:
    await app.bot_data["http"].aclose()


def criar_app(token: str, banco: Banco) -> Application:
    app = (
        Application.builder()
        .token(token)
        .post_init(preparar)
        .post_shutdown(fechar_http)
        .build()
    )
    app.bot_data["banco"] = banco
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("bitcoin", responder_cotacao(cotacoes.BITCOIN)))
    app.add_handler(CommandHandler("dolar", responder_cotacao(cotacoes.DOLAR)))
    app.add_handler(CommandHandler("clima", responder_clima))
    app.add_handler(CommandHandler("lembrar", lembrar))
    return app


def configurar_logs() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    # O httpx registra cada requisição com a URL completa, que contém o token.
    # Subir o nível dele para WARNING evita que o token apareça no terminal.
    logging.getLogger("httpx").setLevel(logging.WARNING)

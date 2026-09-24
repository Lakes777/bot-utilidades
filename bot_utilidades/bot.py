"""Monta o bot: liga cada comando do Telegram à função que responde."""

import logging

import httpx
from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from bot_utilidades import cotacoes

# Aparecem no menu "/" do Telegram e na mensagem de /ajuda.
COMANDOS = [
    BotCommand("bitcoin", "preço do Bitcoin em reais"),
    BotCommand("dolar", "cotação do dólar"),
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


async def preparar(app: Application) -> None:
    # Um único cliente HTTP reaproveita conexões entre os comandos.
    app.bot_data["http"] = httpx.AsyncClient()
    await app.bot.set_my_commands(COMANDOS)


async def fechar_http(app: Application) -> None:
    await app.bot_data["http"].aclose()


def criar_app(token: str) -> Application:
    app = (
        Application.builder()
        .token(token)
        .post_init(preparar)
        .post_shutdown(fechar_http)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("bitcoin", responder_cotacao(cotacoes.BITCOIN)))
    app.add_handler(CommandHandler("dolar", responder_cotacao(cotacoes.DOLAR)))
    return app


def configurar_logs() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    # O httpx registra cada requisição com a URL completa, que contém o token.
    # Subir o nível dele para WARNING evita que o token apareça no terminal.
    logging.getLogger("httpx").setLevel(logging.WARNING)

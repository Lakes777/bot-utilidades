"""Monta o bot: liga cada comando do Telegram à função que responde."""

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

AJUDA = (
    "Comandos disponíveis:\n"
    "/start - apresentação\n"
    "/ajuda - esta lista"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    nome = update.effective_user.first_name
    await update.message.reply_text(
        f"Olá, {nome}! Sou um bot de utilidades.\n\n{AJUDA}"
    )


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(AJUDA)


def criar_app(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    return app


def configurar_logs() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    # O httpx registra cada requisição com a URL completa, que contém o token.
    # Subir o nível dele para WARNING evita que o token apareça no terminal.
    logging.getLogger("httpx").setLevel(logging.WARNING)

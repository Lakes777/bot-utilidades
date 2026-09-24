"""Ponto de entrada: python -m bot_utilidades."""

import sys

from bot_utilidades.bot import configurar_logs, criar_app
from bot_utilidades.config import ConfigError, carregar_token


def main() -> None:
    try:
        token = carregar_token()
    except ConfigError as erro:
        sys.exit(f"Erro: {erro}")

    configurar_logs()
    print("Bot rodando! Mande /start pra ele no Telegram. Ctrl+C para parar.")
    criar_app(token).run_polling()


if __name__ == "__main__":
    main()

"""Ponto de entrada: python -m bot_utilidades."""

import sys

from bot_utilidades.armazenamento import Banco
from bot_utilidades.bot import configurar_logs, criar_app
from bot_utilidades.config import ConfigError, carregar_permitidos, carregar_token


def main() -> None:
    try:
        token = carregar_token()
        permitidos = carregar_permitidos()
    except ConfigError as erro:
        sys.exit(f"Erro: {erro}")

    configurar_logs()
    if permitidos is None:
        print("Aberto para qualquer pessoa (USUARIOS_PERMITIDOS está vazio).")
    else:
        print(f"Só para {len(permitidos)} usuário(s) permitido(s).")
    print("Bot rodando! Mande /start pra ele no Telegram. Ctrl+C para parar.")
    criar_app(token, Banco(), permitidos).run_polling()


if __name__ == "__main__":
    main()

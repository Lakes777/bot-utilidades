"""Ponto de entrada: python -m bot_utilidades."""

import sys

from bot_utilidades.armazenamento import Banco
from bot_utilidades.bot import configurar_logs, criar_app
from bot_utilidades.config import (
    ConfigError,
    carregar_chave_cotacoes,
    carregar_permitidos,
    carregar_spendwise,
    carregar_token,
)


def main() -> None:
    try:
        token = carregar_token()
        permitidos = carregar_permitidos()
        spendwise = carregar_spendwise()
    except ConfigError as erro:
        sys.exit(f"Erro: {erro}")

    configurar_logs()
    if permitidos is None:
        print("Aberto para qualquer pessoa (USUARIOS_PERMITIDOS está vazio).")
    else:
        print(f"Só para {len(permitidos)} usuário(s) permitido(s).")
    print("Bot rodando! Mande /start pra ele no Telegram. Ctrl+C para parar.")
    chave_cotacoes = carregar_chave_cotacoes()
    if chave_cotacoes is None:
        print("Sem AWESOMEAPI_TOKEN: as cotações usam o limite sem cadastro da API.")
    if spendwise is None:
        print("Sem SPENDWISE_CHAVE: o /gasto fica desligado.")
    criar_app(token, Banco(), permitidos, chave_cotacoes, spendwise).run_polling()


if __name__ == "__main__":
    main()

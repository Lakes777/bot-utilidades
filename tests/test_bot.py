from bot_utilidades.bot import criar_app

TOKEN_FALSO = "123456789:" + "A" * 35


def comandos_registrados(app) -> set[str]:
    return {comando for handler in app.handlers[0] for comando in handler.commands}


def test_registra_todos_os_comandos():
    # Montar o app não conecta ao Telegram, então o token falso basta.
    esperados = {"start", "ajuda", "bitcoin", "dolar", "clima"}
    assert esperados <= comandos_registrados(criar_app(TOKEN_FALSO))

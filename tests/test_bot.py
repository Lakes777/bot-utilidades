from bot_utilidades.bot import criar_app

TOKEN_FALSO = "123456789:" + "A" * 35


def comandos_registrados(app) -> set[str]:
    return {comando for handler in app.handlers[0] for comando in handler.commands}


def test_registra_start_e_ajuda():
    # Montar o app não conecta ao Telegram, então o token falso basta.
    assert {"start", "ajuda"} <= comandos_registrados(criar_app(TOKEN_FALSO))

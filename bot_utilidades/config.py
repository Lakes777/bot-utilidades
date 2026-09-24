"""Leitura das configurações (o token do bot) a partir do .env."""

import os
import re
from pathlib import Path

from dotenv import load_dotenv

# Formato dos tokens do @BotFather: "123456789:AAH..." (número, dois-pontos, letras).
FORMATO_TOKEN = re.compile(r"^\d+:[\w-]{30,}$")


class ConfigError(Exception):
    """Configuração ausente ou inválida; a mensagem explica como corrigir."""


def carregar_token(arquivo_env: Path | None = None) -> str:
    """Lê TELEGRAM_TOKEN do .env (ou do ambiente) e confere o formato.

    Uma variável de ambiente já definida tem prioridade sobre o .env,
    o que permite rodar em servidores sem arquivo nenhum.
    """
    load_dotenv(arquivo_env)
    token = os.getenv("TELEGRAM_TOKEN", "").strip()

    if not token:
        raise ConfigError(
            "TELEGRAM_TOKEN não encontrado. Copie o .env.exemplo para .env "
            "e cole nele o token que o @BotFather te deu."
        )
    if not FORMATO_TOKEN.match(token):
        raise ConfigError(
            "TELEGRAM_TOKEN com formato inválido. Ele deve parecer com "
            "123456789:AAH... (confira se não sobrou o texto do exemplo)."
        )
    return token

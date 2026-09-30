"""Leitura das configurações (token e usuários permitidos) a partir do .env."""

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


def carregar_chave_cotacoes(arquivo_env: Path | None = None) -> str | None:
    """Lê AWESOMEAPI_TOKEN, a chave gratuita da API de cotações (opcional).

    Sem chave, a API limita as consultas por endereço, e em servidores na nuvem
    ela costuma recusar logo de cara ("Quota exceeded"). None = sem chave.
    """
    load_dotenv(arquivo_env)
    return os.getenv("AWESOMEAPI_TOKEN", "").strip() or None


def carregar_permitidos(arquivo_env: Path | None = None) -> frozenset[int] | None:
    """Lê USUARIOS_PERMITIDOS (IDs do Telegram separados por vírgula).

    Devolve None quando a variável está vazia: aí o bot fica aberto para todos.
    """
    load_dotenv(arquivo_env)
    texto = os.getenv("USUARIOS_PERMITIDOS", "").strip()
    if not texto:
        return None

    ids = set()
    for parte in re.split(r"[,\s]+", texto):
        if not parte.isdecimal():
            raise ConfigError(
                f'USUARIOS_PERMITIDOS tem um valor inválido: "{parte}". Use os IDs '
                "separados por vírgula, ex.: 123456789,987654321 (cada pessoa "
                "descobre o seu mandando /meuid para o bot)."
            )
        ids.add(int(parte))
    return frozenset(ids)

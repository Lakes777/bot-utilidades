"""Leitura das configurações (token e usuários permitidos) a partir do .env."""

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

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


# O endereço do Spendwise no ar; dá para trocar no .env (ex.: um servidor local).
SPENDWISE_URL_PADRAO = "https://spendwisealp.vercel.app"
# Só ASCII: o \w do Python aceitaria "á", que o cabeçalho HTTP não consegue enviar.
FORMATO_CHAVE_SPENDWISE = re.compile(r"^sw_[A-Za-z0-9_-]{20,}$")


def carregar_spendwise(arquivo_env: Path | None = None) -> tuple[str, str] | None:
    """Lê SPENDWISE_CHAVE (e SPENDWISE_URL, opcional) para o /gasto.

    A chave é criada no site do Spendwise, na janela "Sua conta" > "Chaves de acesso".
    Devolve (url, chave) ou None se a chave não foi configurada.
    """
    load_dotenv(arquivo_env)
    chave = os.getenv("SPENDWISE_CHAVE", "").strip()
    if not chave:
        return None
    if not FORMATO_CHAVE_SPENDWISE.match(chave):
        raise ConfigError(
            "SPENDWISE_CHAVE com formato inválido. Ela começa com sw_ e aparece uma vez só, "
            'quando você cria a chave no Spendwise (Sua conta > Chaves de acesso).'
        )
    return ler_url("SPENDWISE_URL", SPENDWISE_URL_PADRAO), chave


def ler_url(variavel: str, padrao: str) -> str:
    """Lê o endereço de uma API que recebe chave; só aceita https (ou o próprio computador)."""
    url = os.getenv(variavel, "").strip().rstrip("/") or padrao
    partes = urlsplit(url)
    # Sem criptografia, só o próprio computador (o projeto rodando localmente).
    seguro = partes.scheme == "https" or (
        partes.scheme == "http" and partes.hostname in ("localhost", "127.0.0.1")
    )
    if not seguro or not partes.hostname or partes.query or partes.fragment:
        raise ConfigError(
            f"{variavel} precisa ser um endereço https:// sem ? nem # "
            "(a chave não pode ir sem criptografia)."
        )
    return url


COURSEBOOK_URL_PADRAO = "https://coursebookalp.vercel.app"
FORMATO_CHAVE_COURSEBOOK = re.compile(r"^cb_[A-Za-z0-9_-]{20,}$")


def carregar_coursebook(arquivo_env: Path | None = None) -> tuple[str, str] | None:
    """Lê COURSEBOOK_CHAVE (e COURSEBOOK_URL, opcional) para o /prazos.

    A chave é criada no site do Coursebook, na tela Dados > "Chaves de acesso".
    Devolve (url, chave) ou None se a chave não foi configurada.
    """
    load_dotenv(arquivo_env)
    chave = os.getenv("COURSEBOOK_CHAVE", "").strip()
    if not chave:
        return None
    if not FORMATO_CHAVE_COURSEBOOK.match(chave):
        raise ConfigError(
            "COURSEBOOK_CHAVE com formato inválido. Ela começa com cb_ e aparece uma vez só, "
            "quando você cria a chave no Coursebook (tela Dados > Chaves de acesso)."
        )
    return ler_url("COURSEBOOK_URL", COURSEBOOK_URL_PADRAO), chave

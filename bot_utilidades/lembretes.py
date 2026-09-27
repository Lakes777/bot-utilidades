"""Interpreta pedidos de lembrete como "10m tomar água" ou "1h30m reunião".

Não depende do Telegram: só entende o texto. Quem agenda é o bot.
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Horários mostrados e digitados são sempre de Brasília, não importa o fuso do PC.
FUSO = ZoneInfo("America/Sao_Paulo")

# Dias, horas e minutos, nessa ordem, todos opcionais: "2d", "1h30m", "45min"...
FORMATO_TEMPO = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m(?:in)?)?$", re.IGNORECASE)

# Os lembretes ficam salvos no banco, então sobrevivem a reinicializações;
# o limite só evita erros de digitação como "1000d".
PRAZO_MAXIMO = timedelta(days=365)

# O Telegram aceita mensagens de até 4096 caracteres; um lembrete não precisa de tanto.
TAMANHO_MAXIMO = 500

# Máximo de lembretes pendentes por chat, para ninguém encher o banco.
LIMITE_POR_CHAT = 50

USO = "Use assim: /lembrar 10m tomar água\nTempos aceitos: 10m, 2h, 1h30m, 1d"


class LembreteError(Exception):
    """Pedido de lembrete inválido; a mensagem vai para o usuário."""


def ler_tempo(texto: str) -> timedelta:
    """ler_tempo("1h30m") -> timedelta(hours=1, minutes=30)."""
    combinou = FORMATO_TEMPO.match(texto)
    if not combinou or not any(combinou.groups()):
        raise LembreteError(f'Não entendi o tempo "{texto}".\n{USO}')
    dias, horas, minutos = (int(parte or 0) for parte in combinou.groups())
    tempo = timedelta(days=dias, hours=horas, minutes=minutos)

    if tempo < timedelta(minutes=1):
        raise LembreteError("O tempo mínimo é 1 minuto.")
    if tempo > PRAZO_MAXIMO:
        raise LembreteError(f"O tempo máximo é {PRAZO_MAXIMO.days} dias.")
    return tempo


def interpretar(palavras: list[str]) -> tuple[timedelta, str]:
    """["10m", "tomar", "água"] -> (10 minutos, "tomar água")."""
    if len(palavras) < 2:
        raise LembreteError(USO)
    texto = " ".join(palavras[1:])
    if len(texto) > TAMANHO_MAXIMO:
        raise LembreteError(f"O texto do lembrete pode ter até {TAMANHO_MAXIMO} caracteres.")
    return ler_tempo(palavras[0]), texto


def descrever(tempo: timedelta) -> str:
    """descrever(timedelta(hours=1, minutes=30)) -> "1h30min"."""
    horas, segundos = divmod(int(tempo.total_seconds()), 3600)
    dias, horas = divmod(horas, 24)
    minutos = segundos // 60
    partes = [(dias, "d"), (horas, "h"), (minutos, "min")]
    return "".join(f"{valor}{unidade}" for valor, unidade in partes if valor)


def descrever_horario(momento: datetime, agora: datetime) -> str:
    """"às 14:30" se for hoje; "em 28/09 às 14:30" se for outro dia."""
    momento = momento.astimezone(FUSO)
    agora = agora.astimezone(FUSO)
    if momento.date() == agora.date():
        return f"às {momento:%H:%M}"
    if momento.year == agora.year:
        return f"em {momento:%d/%m} às {momento:%H:%M}"
    return f"em {momento:%d/%m/%Y} às {momento:%H:%M}"

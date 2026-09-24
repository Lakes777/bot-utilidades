"""Interpreta pedidos de lembrete como "10m tomar água" ou "1h30m reunião".

Não depende do Telegram: só entende o texto. Quem agenda é o bot.
"""

import re
from datetime import timedelta

# Dias, horas e minutos, nessa ordem, todos opcionais: "2d", "1h30m", "45min"...
FORMATO_TEMPO = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m(?:in)?)?$", re.IGNORECASE)

# Os lembretes ficam na memória do programa; prazos longos demais se perderiam
# se o bot fosse reiniciado.
PRAZO_MAXIMO = timedelta(days=7)

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
        raise LembreteError("O tempo máximo é 7 dias.")
    return tempo


def interpretar(palavras: list[str]) -> tuple[timedelta, str]:
    """["10m", "tomar", "água"] -> (10 minutos, "tomar água")."""
    if len(palavras) < 2:
        raise LembreteError(USO)
    return ler_tempo(palavras[0]), " ".join(palavras[1:])


def descrever(tempo: timedelta) -> str:
    """descrever(timedelta(hours=1, minutes=30)) -> "1h30min"."""
    horas, segundos = divmod(int(tempo.total_seconds()), 3600)
    dias, horas = divmod(horas, 24)
    minutos = segundos // 60
    partes = [(dias, "d"), (horas, "h"), (minutos, "min")]
    return "".join(f"{valor}{unidade}" for valor, unidade in partes if valor)

"""Interpreta pedidos de lembrete como "10m tomar água", "18:30 reunião"
ou "todo dia 8:00 tomar remédio".

Não depende do Telegram: só entende o texto e faz as contas de horário.
Quem salva e agenda é o bot.
"""

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

# Horários mostrados e digitados são sempre de Brasília, não importa o fuso do PC.
FUSO = ZoneInfo("America/Sao_Paulo")

# Dias, horas e minutos, nessa ordem, todos opcionais: "2d", "1h30m", "45min"...
FORMATO_TEMPO = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m(?:in)?)?$", re.IGNORECASE)

# Horário do relógio: "8:00", "18:30". Só com dois-pontos, porque "18h" já quer
# dizer "daqui a 18 horas".
FORMATO_HORARIO = re.compile(r"^(\d{1,2}):(\d{2})$")

# Os lembretes ficam salvos no banco, então sobrevivem a reinicializações;
# o limite só evita erros de digitação como "1000d".
PRAZO_MAXIMO = timedelta(days=365)

# O Telegram aceita mensagens de até 4096 caracteres; um lembrete não precisa de tanto.
TAMANHO_MAXIMO = 500

# Máximo de lembretes pendentes por chat, para ninguém encher o banco.
LIMITE_POR_CHAT = 50

USO = (
    "Use assim:\n"
    "/lembrar 10m tomar água\n"
    "/lembrar 18:30 ligar pra mãe\n"
    "/lembrar todo dia 8:00 tomar remédio\n"
    "Tempos aceitos: 10m, 2h, 1h30m, 1d"
)

USO_CANCELAR = "Use assim: /cancelar 3\nOs números aparecem em /lembretes"

# Na lista, textos longos são cortados para a mensagem caber no limite do Telegram
# mesmo com LIMITE_POR_CHAT lembretes.
TAMANHO_NA_LISTA = 40


class LembreteError(Exception):
    """Pedido de lembrete inválido; a mensagem vai para o usuário."""


@dataclass(frozen=True)
class Pedido:
    quando: datetime
    texto: str
    diario: bool = False
    tempo: timedelta | None = None  # preenchido só em "daqui a X" ("10m", "2h"...)


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


def ler_horario(texto: str) -> time:
    """ler_horario("8:05") -> time(8, 5)."""
    combinou = FORMATO_HORARIO.match(texto)
    if not combinou:
        raise LembreteError(f'Não entendi o horário "{texto}". Use, por exemplo, 8:00 ou 18:30.')
    horas, minutos = int(combinou[1]), int(combinou[2])
    if horas > 23 or minutos > 59:
        raise LembreteError(f'O horário "{texto}" não existe.')
    return time(horas, minutos)


def proxima_vez(horario: time, agora: datetime) -> datetime:
    """A próxima vez que o relógio de Brasília marca o horário: hoje ou amanhã."""
    agora = agora.astimezone(FUSO)
    momento = datetime.combine(agora.date(), horario, tzinfo=FUSO)
    if momento <= agora:
        momento = datetime.combine(agora.date() + timedelta(days=1), horario, tzinfo=FUSO)
    return momento


def interpretar(palavras: list[str], agora: datetime) -> Pedido:
    """["10m", "tomar", "água"] -> Pedido(quando=agora + 10 minutos, texto="tomar água").

    Também entende ["18:30", ...] (horário fixo) e ["todo", "dia", "8:00", ...] (diário).
    """
    diario = [p.lower() for p in palavras[:2]] == ["todo", "dia"]
    if diario:
        palavras = palavras[2:]

    if len(palavras) < 2:
        raise LembreteError(USO)
    texto = " ".join(palavras[1:])
    if len(texto) > TAMANHO_MAXIMO:
        raise LembreteError(f"O texto do lembrete pode ter até {TAMANHO_MAXIMO} caracteres.")

    if FORMATO_HORARIO.match(palavras[0]) or diario:
        return Pedido(proxima_vez(ler_horario(palavras[0]), agora), texto, diario=diario)

    tempo = ler_tempo(palavras[0])
    return Pedido(agora + tempo, texto, tempo=tempo)


def confirmar(pedido: Pedido, agora: datetime) -> str:
    """A mensagem que o bot responde depois de salvar o pedido."""
    quando = pedido.quando.astimezone(FUSO)
    dia = "hoje" if quando.date() == agora.astimezone(FUSO).date() else "amanhã"

    if pedido.diario:
        return (
            f"✅ Combinado! Todo dia às {quando:%H:%M} eu te lembro: {pedido.texto}\n"
            f"O primeiro é {dia}."
        )
    if pedido.tempo is None:
        return f"✅ Combinado! {dia.capitalize()} às {quando:%H:%M} eu te lembro: {pedido.texto}"
    return (
        f"✅ Combinado! Daqui a {descrever(pedido.tempo)} "
        f"({descrever_horario(quando, agora)}) eu te lembro: {pedido.texto}"
    )


def ler_numero(palavras: list[str]) -> int:
    """["3"] ou ["#3"] -> 3."""
    if len(palavras) != 1:
        raise LembreteError(USO_CANCELAR)
    numero = palavras[0].removeprefix("#")
    if not numero.isdecimal():
        raise LembreteError(USO_CANCELAR)
    return int(numero)


def encurtar(texto: str, tamanho: int = TAMANHO_NA_LISTA) -> str:
    """encurtar("pagar o boleto da faculdade", 10) -> "pagar o b…"."""
    return texto if len(texto) <= tamanho else texto[: tamanho - 1] + "…"


def descrever(tempo: timedelta) -> str:
    """descrever(timedelta(hours=1, minutes=30)) -> "1h30min"."""
    horas, segundos = divmod(int(tempo.total_seconds()), 3600)
    dias, horas = divmod(horas, 24)
    minutos = segundos // 60
    partes = [(dias, "d"), (horas, "h"), (minutos, "min")]
    return "".join(f"{valor}{unidade}" for valor, unidade in partes if valor)


def data_e_hora(momento: datetime, agora: datetime) -> str:
    """"hoje às 14:30", "28/09 às 14:30" ou, em outro ano, "02/01/2027 às 09:00"."""
    momento = momento.astimezone(FUSO)
    agora = agora.astimezone(FUSO)
    if momento.date() == agora.date():
        return f"hoje às {momento:%H:%M}"
    data = f"{momento:%d/%m}" if momento.year == agora.year else f"{momento:%d/%m/%Y}"
    return f"{data} às {momento:%H:%M}"


def descrever_horario(momento: datetime, agora: datetime) -> str:
    """"às 14:30" se for hoje; "em 28/09 às 14:30" se for outro dia."""
    texto = data_e_hora(momento, agora)
    return texto.removeprefix("hoje ") if texto.startswith("hoje ") else f"em {texto}"

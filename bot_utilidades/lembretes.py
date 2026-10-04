"""Interpreta pedidos de lembrete como "10m tomar água", "18:30 reunião",
"25/12 9:00 ligar pra vó", "todo dia 8:00 tomar remédio" ou "toda quinta 19:00 futebol".

Não depende do Telegram: só entende o texto e faz as contas de horário.
Quem salva e agenda é o bot.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# Horários mostrados e digitados são sempre de Brasília, não importa o fuso do PC.
FUSO = ZoneInfo("America/Sao_Paulo")

# Dias, horas e minutos, nessa ordem, todos opcionais: "2d", "1h30m", "45min"...
FORMATO_TEMPO = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m(?:in)?)?$", re.IGNORECASE)

# Horário do relógio: "8:00", "18:30". Só com dois-pontos, porque "18h" já quer
# dizer "daqui a 18 horas".
FORMATO_HORARIO = re.compile(r"^(\d{1,2}):(\d{2})$")

# Data: "25/12", "25/12/2026" ou "25/12/26".
FORMATO_DATA = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?$")

# "20h", "9h30": depois de uma data, quase certamente é um horário mal escrito.
PARECE_HORARIO = re.compile(r"^\d{1,2}h(\d{2})?$", re.IGNORECASE)

# Horário usado quando a data vem sem horário: "/lembrar 25/12 aniversário".
HORARIO_PADRAO = time(9, 0)

# Até onde uma data com ano pode ir; também só evita erros de digitação ("25/12/2226").
ANOS_MAXIMOS = 5

# Dias da semana na ordem do Python (segunda = 0), sem acento, com as abreviações.
DIAS_DA_SEMANA = {
    "segunda": 0, "seg": 0,
    "terca": 1, "ter": 1,
    "quarta": 2, "qua": 2,
    "quinta": 3, "qui": 3,
    "sexta": 4, "sex": 4,
    "sabado": 5, "sab": 5,
    "domingo": 6, "dom": 6,
}
NOMES_DOS_DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

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
    "/lembrar 25/12 9:00 ligar pra vó\n"
    "/lembrar todo dia 8:00 tomar remédio\n"
    "/lembrar toda quinta 19:00 futebol\n"
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
    semanal: bool = False  # repete toda semana no mesmo dia e horário
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


def ler_data(texto: str, horario: time | None, agora: datetime) -> datetime:
    """ler_data("25/12", time(20, 30), agora) -> 25/12 às 20:30 deste ano, ou do próximo se já passou.

    Sem horário (None), usa o HORARIO_PADRAO.
    """
    combinou = FORMATO_DATA.match(texto)
    if not combinou:
        raise LembreteError(f'Não entendi a data "{texto}". Use, por exemplo, 25/12 ou 25/12/2026.')
    dia, mes = int(combinou[1]), int(combinou[2])
    agora = agora.astimezone(FUSO)
    hora_certa = horario or HORARIO_PADRAO

    def montar(ano: int) -> datetime | None:
        try:
            return datetime.combine(date(ano, mes, dia), hora_certa, tzinfo=FUSO)
        except ValueError:
            return None

    if combinou[3] is not None:
        ano = int(combinou[3])
        momento = montar(ano + 2000 if ano < 100 else ano)
        if momento is None:
            raise LembreteError(f'A data "{texto}" não existe.')
        if momento.date() < agora.date():
            raise LembreteError(f'A data "{texto}" já passou.')
        if momento.year > agora.year + ANOS_MAXIMOS:
            raise LembreteError(f"A data pode ser no máximo {ANOS_MAXIMOS} anos à frente.")
    else:
        # Sem ano: a próxima vez que a data chega. 29/02 pode pular alguns anos.
        candidatos = [montar(ano) for ano in range(agora.year, agora.year + ANOS_MAXIMOS)]
        candidatos = [m for m in candidatos if m is not None and m.date() >= agora.date()]
        if not candidatos:
            raise LembreteError(f'A data "{texto}" não existe.')
        momento = candidatos[0]

    if momento <= agora:
        # Só acontece com a data de hoje. "27/09 8:00" às 10:00 do dia 27 é engano,
        # não um lembrete para daqui a um ano.
        if horario is None:
            raise LembreteError(
                f"Sem horário, o lembrete fica para as {HORARIO_PADRAO:%H:%M}, que hoje já passou. "
                f"Escreva o horário, por exemplo: /lembrar {texto} 23:00 ..."
            )
        raise LembreteError(f"O horário {horario:%H:%M} de hoje já passou.")
    return momento


def sem_acento(texto: str) -> str:
    """sem_acento("Sábado") -> "sabado"."""
    decomposto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def ler_dia_da_semana(palavra: str) -> int | None:
    """"quinta", "Quinta-feira", "quintas", "sáb" -> número do dia (segunda = 0); None se não for dia."""
    palavra = sem_acento(palavra).removesuffix("-feiras").removesuffix("-feira")
    if palavra not in DIAS_DA_SEMANA:
        palavra = palavra.removesuffix("s")  # plural: "todas as quintas", "todos os sábados"
    return DIAS_DA_SEMANA.get(palavra)


def toda_semana(dia: int) -> str:
    """toda_semana(3) -> "toda quinta"; toda_semana(5) -> "todo sábado"."""
    return ("todo " if dia >= 5 else "toda ") + NOMES_DOS_DIAS[dia]


def proxima_vez_no_dia(dia: int, horario: time, agora: datetime) -> datetime:
    """A próxima vez que for aquele dia da semana naquele horário, em Brasília."""
    agora = agora.astimezone(FUSO)
    faltam = (dia - agora.weekday()) % 7
    momento = datetime.combine(agora.date() + timedelta(days=faltam), horario, tzinfo=FUSO)
    if momento <= agora:
        momento += timedelta(days=7)
    return momento


def interpretar(palavras: list[str], agora: datetime) -> Pedido:
    """["10m", "tomar", "água"] -> Pedido(quando=agora + 10 minutos, texto="tomar água").

    Também entende ["18:30", ...] (horário fixo), ["25/12", "9:00", ...] (data, com
    horário opcional, também "25/12 às 9:00"), ["todo", "dia", "8:00", ...] (diário)
    e ["toda", "quinta", "19:00", ...] (semanal).
    """
    if palavras and sem_acento(palavras[0]) in ("toda", "todo", "todas", "todos"):
        resto = palavras[1:]
        if resto and sem_acento(resto[0]) in ("as", "os"):  # "todas as quintas"
            resto = resto[1:]
        dia = ler_dia_da_semana(resto[0]) if resto else None
        if dia is not None:
            return interpretar_semanal(dia, resto[1:], agora)

    diario = [p.lower() for p in palavras[:2]] == ["todo", "dia"]
    if diario:
        palavras = palavras[2:]

    if not diario and palavras and FORMATO_DATA.match(palavras[0]):
        return interpretar_data(palavras, agora)

    if len(palavras) < 2:
        raise LembreteError(USO)
    texto = ler_texto(palavras[1:])

    if FORMATO_HORARIO.match(palavras[0]) or diario:
        return Pedido(proxima_vez(ler_horario(palavras[0]), agora), texto, diario=diario)

    tempo = ler_tempo(palavras[0])
    return Pedido(agora + tempo, texto, tempo=tempo)


def interpretar_data(palavras: list[str], agora: datetime) -> Pedido:
    """["25/12", "às", "20:30", "ceia"] ou ["25/12", "ceia"] (às 9:00)."""
    data, resto = palavras[0], palavras[1:]
    com_as = bool(resto) and resto[0].lower() in ("às", "as")
    if com_as:
        resto = resto[1:]

    horario = None
    if resto and (com_as or FORMATO_HORARIO.match(resto[0])):
        horario = ler_horario(resto[0])
        resto = resto[1:]
    elif resto and PARECE_HORARIO.match(resto[0]):
        # "25/12 20h ceia" viraria 9:00 com o texto "20h ceia": melhor avisar.
        raise LembreteError(f'Escreva o horário com dois-pontos: 20:30 em vez de "{resto[0]}".')

    if not resto:
        raise LembreteError(USO)
    return Pedido(ler_data(data, horario, agora), ler_texto(resto))


def interpretar_semanal(dia: int, palavras: list[str], agora: datetime) -> Pedido:
    """dia=3, ["19:00", "futebol"] ou ["feira", "às", "19:00", "futebol"]."""
    if palavras and sem_acento(palavras[0]) in ("feira", "feiras"):  # "toda quinta feira", sem hífen
        palavras = palavras[1:]
    if palavras and sem_acento(palavras[0]) == "as":
        palavras = palavras[1:]
    if len(palavras) < 2:
        raise LembreteError(USO)
    horario = ler_horario(palavras[0])
    return Pedido(proxima_vez_no_dia(dia, horario, agora), ler_texto(palavras[1:]), semanal=True)


def ler_texto(palavras: list[str]) -> str:
    texto = " ".join(palavras)
    if len(texto) > TAMANHO_MAXIMO:
        raise LembreteError(f"O texto do lembrete pode ter até {TAMANHO_MAXIMO} caracteres.")
    return texto


def confirmar(pedido: Pedido, agora: datetime) -> str:
    """A mensagem que o bot responde depois de salvar o pedido."""
    quando = pedido.quando.astimezone(FUSO)
    hoje = agora.astimezone(FUSO).date()
    if quando.date() == hoje:
        dia = "hoje"
    elif quando.date() == hoje + timedelta(days=1):
        dia = "amanhã"
    else:
        dia = None

    if pedido.semanal:
        formato = "%d/%m" if quando.year == hoje.year else "%d/%m/%Y"
        primeiro = dia or f"em {quando:{formato}}"
        return (
            f"✅ Combinado! {toda_semana(quando.weekday()).capitalize()} às {quando:%H:%M} "
            f"eu te lembro: {pedido.texto}\nO primeiro é {primeiro}."
        )
    if pedido.diario:
        return (
            f"✅ Combinado! Todo dia às {quando:%H:%M} eu te lembro: {pedido.texto}\n"
            f"O primeiro é {dia}."
        )
    if pedido.tempo is None and dia is None:
        return f"✅ Combinado! Em {data_e_hora(quando, agora)} eu te lembro: {pedido.texto}"
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

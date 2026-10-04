"""Interpreta pedidos de lembrete como "10m tomar água", "18:30 reunião",
"25/12 9:00 ligar pra vó", "todo dia 8:00 tomar remédio" ou "toda quinta 19:00 futebol".

Não depende do Telegram: só entende o texto e faz as contas de horário.
Quem salva e agenda é o bot.
"""

import calendar
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

# Horário do aviso de chuva quando o /chuva vem sem horário.
HORARIO_CHUVA = time(7, 0)

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
DIAS_UTEIS = (0, 1, 2, 3, 4)
FIM_DE_SEMANA = (5, 6)

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
    "/lembrar toda seg e qua 7:00 academia\n"
    "/lembrar dias úteis 7:00 acordar\n"
    "/lembrar todo dia 10 9:00 pagar aluguel\n"
    "Tempos aceitos: 10m, 2h, 1h30m, 1d"
)

USO_CANCELAR = "Use assim: /cancelar 3\nOs números aparecem em /lembretes"

USO_MUDAR = (
    "Use assim:\n"
    "/mudar 3 20:00 (mantém a repetição, se houver)\n"
    "/mudar 3 25/12 9:00\n"
    "/mudar 3 toda sexta 18:00\n"
    "Os números aparecem em /lembretes"
)

# Ocupa o lugar do texto quando /mudar reaproveita o interpretar() do /lembrar.
_SEM_TEXTO = "\x00"

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
    semanal: bool = False  # repete toda semana, nos dias de "dias", no mesmo horário
    dias: tuple[int, ...] = ()  # dias da semana (segunda = 0), só nos semanais
    dia_do_mes: int | None = None  # preenchido só nos mensais ("todo dia 10")
    sem_horario: bool = False  # o horário não foi digitado e ficou o padrão
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


def toda_semana(dias: tuple[int, ...]) -> str:
    """(3,) -> "toda quinta"; (0, 2) -> "toda segunda e quarta"; (5,) -> "todo sábado"."""
    if dias == DIAS_UTEIS:
        return "todo dia útil"
    if dias == FIM_DE_SEMANA:
        return "todo fim de semana"
    if len(dias) == 7:
        return "todo dia"
    nomes = [NOMES_DOS_DIAS[dia] for dia in dias]
    lista = nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]
    return ("todo " if dias[0] >= 5 else "toda ") + lista


def proxima_vez_no_dia(dia: int, horario: time, agora: datetime) -> datetime:
    """A próxima vez que for aquele dia da semana naquele horário, em Brasília."""
    agora = agora.astimezone(FUSO)
    faltam = (dia - agora.weekday()) % 7
    momento = datetime.combine(agora.date() + timedelta(days=faltam), horario, tzinfo=FUSO)
    if momento <= agora:
        momento += timedelta(days=7)
    return momento


def proxima_vez_nos_dias(dias: tuple[int, ...], horario: time, agora: datetime) -> datetime:
    """A mais próxima entre as próximas vezes de cada dia."""
    return min(proxima_vez_no_dia(dia, horario, agora) for dia in dias)


def ler_dias(palavras: list[str]) -> tuple[tuple[int, ...], bool, list[str]] | None:
    """Lê os dias da semana do começo do pedido.

    Devolve (dias, repete, resto) ou None se o pedido não começa com dias da semana.
    ["toda", "seg", "e", "qua", "7:00", ...] -> ((0, 2), True, ["7:00", ...])
    ["dias", "úteis", "7:00", ...] -> ((0, 1, 2, 3, 4), True, ["7:00", ...])
    ["quinta", "19:00", ...] -> ((3,), False, ["19:00", ...])  (só uma vez)
    """
    palavras = separar_virgulas(palavras)
    palavra = [sem_acento(p).rstrip(",") for p in palavras]
    i = 0
    repete = bool(palavra) and palavra[0] in ("toda", "todo", "todas", "todos")
    if repete:
        i = 2 if palavra[1:2] in (["as"], ["os"]) else 1  # "todas as quintas"

    if palavra[i : i + 2] in (["dia", "util"], ["dias", "uteis"]):
        return DIAS_UTEIS, True, palavras[i + 2 :]
    if palavra[i : i + 3] in (["fim", "de", "semana"], ["fins", "de", "semana"]):
        return FIM_DE_SEMANA, True, palavras[i + 3 :]

    if i >= len(palavra) or ler_dia_da_semana(palavra[i]) is None:
        return None
    dias = [ler_dia_da_semana(palavra[i])]
    i += 1
    while i < len(palavra):
        if palavra[i] in ("feira", "feiras"):  # "quinta feira", sem hífen
            i += 1
            continue
        seguinte = ler_dia_da_semana(palavra[i + 1]) if i + 1 < len(palavra) else None
        if palavra[i] == "a" and seguinte is not None:  # "seg a sex"
            # "seg a seg" dá a volta inteira: a semana toda.
            tamanho = (seguinte - dias[-1]) % 7 or 7
            dias += [(dias[-1] + n) % 7 for n in range(1, tamanho + 1)]
            i += 2
        elif palavra[i] == "e" and seguinte is not None:  # "seg e qua"
            dias.append(seguinte)
            i += 2
        elif palavras[i - 1].endswith(",") and ler_dia_da_semana(palavra[i]) is not None:
            dias.append(ler_dia_da_semana(palavra[i]))  # "seg, qua e sex"
            i += 1
        else:
            break
    return tuple(sorted(set(dias))), repete, palavras[i:]


def separar_virgulas(palavras: list[str]) -> list[str]:
    """["seg,qua", "7:00", "a,b"] -> ["seg,", "qua", "7:00", "a,b"].

    Só separa palavras feitas de dias da semana, e só antes do horário,
    para não mexer nas vírgulas do texto do lembrete.
    """
    resultado = []
    for posicao, palavra in enumerate(palavras):
        partes = palavra.split(",")
        dias = [parte for parte in partes if parte]
        if FORMATO_HORARIO.match(palavra) or len(partes) < 2 or not dias or any(
            ler_dia_da_semana(parte) is None for parte in dias
        ):
            if FORMATO_HORARIO.match(palavra):
                return resultado + palavras[posicao:]
            resultado.append(palavra)
            continue
        for numero, parte in enumerate(partes):
            if parte:
                resultado.append(parte + ("," if numero < len(partes) - 1 else ""))
    return resultado


def proxima_vez_no_mes(dia: int, horario: time, agora: datetime) -> datetime:
    """A próxima vez do dia do mês naquele horário; nos meses curtos, o último dia."""
    agora = agora.astimezone(FUSO)
    ano, mes = agora.year, agora.month
    while True:
        ultimo = calendar.monthrange(ano, mes)[1]
        momento = datetime.combine(date(ano, mes, min(dia, ultimo)), horario, tzinfo=FUSO)
        if momento > agora:
            return momento
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)


def ler_mensal(palavras: list[str]) -> tuple[int, list[str]] | None:
    """["todo", "dia", "10", ...] ou ["todo", "mês", "no", "dia", "10", ...] -> (10, resto)."""
    palavra = [sem_acento(p).rstrip(",") for p in palavras]
    if palavra[:2] == ["todo", "mes"]:
        i = 3 if palavra[2:3] == ["no"] else 2
        if palavra[i : i + 1] != ["dia"]:
            return None
        i += 1
    elif palavra[:2] == ["todo", "dia"]:
        i = 2
    else:
        return None
    if i >= len(palavras) or not palavras[i].isdecimal():
        return None  # "todo dia 8:00" é o diário
    dia = int(palavras[i])
    if not 1 <= dia <= 31:
        raise LembreteError(f"O dia do mês vai de 1 a 31, não {dia}.")
    return dia, palavras[i + 1 :]


def interpretar(palavras: list[str], agora: datetime) -> Pedido:
    """["10m", "tomar", "água"] -> Pedido(quando=agora + 10 minutos, texto="tomar água").

    Também entende ["18:30", ...] (horário fixo), ["25/12", "9:00", ...] (data, com
    horário opcional, também "25/12 às 9:00"), ["todo", "dia", "8:00", ...] (diário)
    ["toda", "quinta", "19:00", ...] (semanal) e ["todo", "dia", "10", "9:00", ...] (mensal).
    """
    lidos = ler_dias(palavras)
    if lidos is not None:
        return interpretar_semanal(*lidos, agora)

    mensal = ler_mensal(palavras)
    if mensal is not None:
        return interpretar_mensal(*mensal, agora)

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


def interpretar_semanal(
    dias: tuple[int, ...], repete: bool, palavras: list[str], agora: datetime
) -> Pedido:
    """dias=(3,), ["19:00", "futebol"] ou ["às", "19:00", "futebol"]."""
    if palavras and sem_acento(palavras[0]) == "as":
        palavras = palavras[1:]
    if len(palavras) < 2:
        raise LembreteError(USO)
    if not repete and len(dias) > 1:
        # "seg e qua 7:00" sem "toda" é ambíguo: uma vez só ou toda semana?
        raise LembreteError(
            f'Para repetir toda semana, comece com "toda": /lembrar {toda_semana(dias)} ...'
        )
    if not FORMATO_HORARIO.match(palavras[0]):
        exemplo = toda_semana(dias) if repete else NOMES_DOS_DIAS[dias[0]]
        raise LembreteError(
            f'Não entendi o horário "{palavras[0]}". Depois dos dias vem o horário, '
            f"por exemplo: /lembrar {exemplo} 7:00 ..."
        )
    horario = ler_horario(palavras[0])
    quando = proxima_vez_nos_dias(dias, horario, agora)
    if not repete:  # "quinta 19:00 dentista": só a próxima quinta
        return Pedido(quando, ler_texto(palavras[1:]))
    return Pedido(quando, ler_texto(palavras[1:]), semanal=True, dias=dias)


def interpretar_mensal(dia: int, palavras: list[str], agora: datetime) -> Pedido:
    """dia=10, ["9:00", "aluguel"], ["às", "9:00", "aluguel"] ou ["aluguel"] (às 9:00)."""
    if palavras and sem_acento(palavras[0]) == "as":
        if len(palavras) < 3:
            raise LembreteError(USO)
        horario = ler_horario(palavras[1])
        palavras = palavras[2:]
    elif palavras and FORMATO_HORARIO.match(palavras[0]):
        horario = ler_horario(palavras[0])
        palavras = palavras[1:]
    elif palavras and PARECE_HORARIO.match(palavras[0]):
        # "todo dia 10 20h aluguel" viraria 9:00 com o texto "20h aluguel".
        raise LembreteError(f'Escreva o horário com dois-pontos: 20:30 em vez de "{palavras[0]}".')
    else:
        horario = None
    if not palavras:
        raise LembreteError(USO)
    quando = proxima_vez_no_mes(dia, horario or HORARIO_PADRAO, agora)
    return Pedido(quando, ler_texto(palavras), dia_do_mes=dia, sem_horario=horario is None)


def ler_texto(palavras: list[str]) -> str:
    texto = " ".join(palavras)
    if len(texto) > TAMANHO_MAXIMO:
        raise LembreteError(f"O texto do lembrete pode ter até {TAMANHO_MAXIMO} caracteres.")
    return texto


def avisos_do_mensal(pedido: Pedido) -> str:
    """Linhas extras da confirmação de um mensal (vazio se não for mensal)."""
    dia = pedido.dia_do_mes
    if dia is None:
        return ""
    aviso = ""
    if dia > 28:
        aviso += f"\nNos meses sem dia {dia}, vem no último dia do mês."
    if pedido.sem_horario and dia <= 23:
        # "todo dia 8 remédio" quase sempre queria dizer 8h, todo dia.
        texto = "" if pedido.texto == _SEM_TEXTO else f" {pedido.texto}"
        comando = "/mudar N" if not texto else "/lembrar"
        aviso += f"\nSe queria todo dia às {dia}h, use {comando} todo dia {dia}:00{texto}"
    return aviso


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

    formato = "%d/%m" if quando.year == hoje.year else "%d/%m/%Y"
    primeiro = dia or f"em {quando:{formato}}"
    if pedido.dia_do_mes is not None:
        aviso = avisos_do_mensal(pedido)
        return (
            f"✅ Combinado! Todo mês, no dia {pedido.dia_do_mes}, às {quando:%H:%M}, "
            f"eu te lembro: {pedido.texto}\nO primeiro é {primeiro}.{aviso}"
        )
    if pedido.semanal:
        return (
            f"✅ Combinado! {toda_semana(pedido.dias).capitalize()} às {quando:%H:%M} "
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


def ler_numero(palavras: list[str], uso: str = USO_CANCELAR) -> int:
    """["3"] ou ["#3"] -> 3."""
    if len(palavras) != 1:
        raise LembreteError(uso)
    numero = palavras[0].removeprefix("#")
    if not numero.isdecimal():
        raise LembreteError(uso)
    return int(numero)


def interpretar_mudanca(palavras: list[str], agora: datetime) -> tuple[int, Pedido | time]:
    """["3", "20:00"] -> (3, time(20, 0)); ["3", "25/12", "9:00"] -> (3, Pedido(...)).

    Só um horário vira time: quem chama decide se mantém a repetição do lembrete.
    O resto usa o mesmo formato do /lembrar, sem o texto.
    """
    numero = ler_numero(palavras[:1], USO_MUDAR)
    quando = palavras[1:]
    if not quando:
        raise LembreteError(USO_MUDAR)
    if len(quando) == 1 and FORMATO_HORARIO.match(quando[0]):
        return numero, ler_horario(quando[0])
    try:
        pedido = interpretar([*quando, _SEM_TEXTO], agora)
    except LembreteError as erro:
        mensagem = str(erro)
        if _SEM_TEXTO in mensagem or mensagem == USO:
            raise LembreteError(USO_MUDAR) from None
        if USO in mensagem:  # "Não entendi o tempo ... Use assim: /lembrar ..."
            raise LembreteError(mensagem.replace(USO, USO_MUDAR)) from None
        raise
    if pedido.texto != _SEM_TEXTO:  # sobrou texto: "/mudar 3 20:00 outra coisa"
        raise LembreteError("O /mudar troca só o quando, não o texto.\n" + USO_MUDAR)
    return numero, pedido


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

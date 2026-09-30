"""Interpreta pedidos de alerta de preço como "bitcoin acima 400000" ou
"dolar abaixo 5,20" e decide quando um alerta foi atingido.

Não depende do Telegram: quem salva, confere a cotação e avisa é o bot.
"""

import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from bot_utilidades.cotacoes import BITCOIN, DOLAR, Moeda, reais

# De quanto em quanto tempo o bot confere as cotações. A AwesomeAPI é gratuita e
# limita consultas seguidas; com uma consulta por moeda, 5 minutos é folgado.
INTERVALO = timedelta(minutes=5)

# Máximo de alertas pendentes por chat, para ninguém encher o banco.
LIMITE_POR_CHAT = 10

MOEDAS = {"bitcoin": BITCOIN, "btc": BITCOIN, "dolar": DOLAR, "dólar": DOLAR, "usd": DOLAR}
POR_PAR = {moeda.par: moeda for moeda in MOEDAS.values()}

# Só dígitos, pontos e vírgulas: "4e5" e "1e30" (notação científica) não são jeito de
# digitar preço, e um número gigante passaria da precisão do Decimal ao formatar.
FORMATO_VALOR = re.compile(r"^[\d.,]+$")
DIGITOS_MAXIMOS = 12  # na parte inteira: até R$ 999 bilhões

# Um valor mais de 10 vezes longe do preço atual quase sempre é erro de digitação
# ("5.500" no dólar vira 5500; "400,000" no bitcoin vira 400 reais).
DISTANCIA_MAXIMA = 10

ACIMA, ABAIXO = "acima", "abaixo"
DIRECOES = {"acima": ACIMA, ">": ACIMA, "abaixo": ABAIXO, "<": ABAIXO}

USO = (
    "Use assim:\n"
    "/alerta bitcoin acima 400000\n"
    "/alerta dolar abaixo 5,20\n"
    "Moedas: bitcoin (ou btc) e dolar (ou usd)"
)


class AlertaError(Exception):
    """Pedido que não deu para entender; a mensagem vai para o usuário."""


@dataclass(frozen=True)
class PedidoAlerta:
    moeda: Moeda
    direcao: str  # ACIMA ou ABAIXO
    valor: Decimal


def ler_valor(texto: str) -> Decimal:
    """Aceita "400000", "400.000", "400.000,50", "5,20", "5.20" e "R$ 5,20" junto.

    Com vírgula, ela separa os centavos e os pontos são de milhar. Sem vírgula,
    um ponto seguido de exatamente 3 dígitos é de milhar ("400.000"); senão,
    separa os centavos ("5.20").
    """
    limpo = texto.lower().removeprefix("r$").strip()
    if not FORMATO_VALOR.match(limpo):
        raise AlertaError(f"Não entendi o valor {texto!r}.\n\n{USO}")
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif limpo.count(".") > 1 or (limpo.count(".") == 1 and len(limpo.split(".")[1]) == 3):
        limpo = limpo.replace(".", "")
    try:
        valor = Decimal(limpo)
    except InvalidOperation:
        raise AlertaError(f"Não entendi o valor {texto!r}.\n\n{USO}")
    if valor <= 0:
        raise AlertaError("O valor precisa ser maior que zero.")
    if valor >= 10**DIGITOS_MAXIMOS:
        raise AlertaError("Esse valor é grande demais.")
    return valor


def longe_demais(valor: Decimal, preco: Decimal) -> bool:
    """Se o valor está mais de DISTANCIA_MAXIMA vezes acima ou abaixo do preço."""
    return valor > preco * DISTANCIA_MAXIMA or valor * DISTANCIA_MAXIMA < preco


def interpretar(args: list[str]) -> PedidoAlerta:
    """["bitcoin", "acima", "400000"] -> PedidoAlerta(BITCOIN, ACIMA, 400000)."""
    if len(args) == 4 and args[2].lower() == "r$":  # "/alerta dolar abaixo R$ 5,20"
        args = [*args[:2], args[3]]
    if len(args) != 3:
        raise AlertaError(USO)
    nome, direcao, valor = args
    moeda = MOEDAS.get(nome.lower())
    if moeda is None:
        raise AlertaError(f"Não conheço a moeda {nome!r}.\n\n{USO}")
    if direcao.lower() not in DIRECOES:
        raise AlertaError(f"Use acima ou abaixo, não {direcao!r}.\n\n{USO}")
    return PedidoAlerta(moeda, DIRECOES[direcao.lower()], ler_valor(valor))


def atingiu(direcao: str, valor: Decimal, preco: Decimal) -> bool:
    """Se o preço chegou ao valor do alerta (igual também conta)."""
    return preco >= valor if direcao == ACIMA else preco <= valor


def descrever(moeda: Moeda, direcao: str, valor: Decimal) -> str:
    """Ex.: 'Bitcoin acima de R$ 400.000,00'."""
    return f"{moeda.nome} {direcao} de {reais(valor, moeda.casas)}"


def aviso(moeda: Moeda, direcao: str, valor: Decimal, preco: Decimal) -> str:
    """A mensagem de quando o alerta dispara."""
    return (
        f"🔔 Alerta: {descrever(moeda, direcao, valor)}\n"
        f"Agora está em {reais(preco, moeda.casas)}."
    )

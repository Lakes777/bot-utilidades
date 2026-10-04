"""Interpreta pedidos de conversão como "100 usd", "0,5 btc" ou "500 reais para dolar"
e faz as contas com as cotações em reais.

Não depende do Telegram: quem busca as cotações e responde é o bot.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from bot_utilidades.alertas import AlertaError, ler_valor
from bot_utilidades.cotacoes import BITCOIN, DOLAR, Moeda, arredondar, reais


@dataclass(frozen=True)
class Unidade:
    codigo: str
    simbolo: str
    casas: int
    moeda: Moeda | None  # None = o próprio real, que não precisa de cotação


REAL = Unidade("BRL", "R$", 2, None)
DOLARES = Unidade("USD", "US$", 2, DOLAR)
BITCOINS = Unidade("BTC", "₿", 8, BITCOIN)

NOMES = {
    "brl": REAL, "real": REAL, "reais": REAL, "r$": REAL,
    "usd": DOLARES, "dolar": DOLARES, "dolares": DOLARES, "us$": DOLARES,
    "btc": BITCOINS, "bitcoin": BITCOINS, "bitcoins": BITCOINS,
}
LIGACOES = {"em", "para", "pra", "p/", "->", "=", "to"}

USO = (
    "Use assim:\n"
    "/converter 100 usd (dólar para real)\n"
    "/converter 0,5 btc\n"
    "/converter 500 reais para dolar\n"
    "/converter 100 usd em btc\n"
    "Moedas: real (brl), dólar (usd) e bitcoin (btc). Centavos com vírgula: 5,20"
)


class ConversorError(Exception):
    """Pedido inválido; a mensagem vai para o usuário."""


@dataclass(frozen=True)
class Pedido:
    valor: Decimal
    origem: Unidade
    destinos: tuple[Unidade, ...]


def sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def ler_quantia(texto: str, ponto_decimal: bool = False) -> Decimal:
    """Como o ler_valor dos alertas ("1.000" é mil), com duas exceções: "0.005" é
    decimal, e com ponto_decimal (usado no bitcoin) um ponto só é sempre decimal:
    ninguém quer dizer "1.005 btc" como mil e cinco bitcoins."""
    if re.fullmatch(r"0\.[\d.]*", texto) and texto.count(".") > 1:
        raise ConversorError(f"Não entendi o valor {texto!r}.\n\n{USO}")  # "0.5.1"
    if re.fullmatch(r"0\.\d+", texto) or (ponto_decimal and re.fullmatch(r"\d+\.\d+", texto)):
        valor = Decimal(texto)
        if valor <= 0:
            raise ConversorError("O valor precisa ser maior que zero.")
        return valor
    try:
        return ler_valor(texto)
    except AlertaError as erro:
        mensagem = str(erro).split("\n\n")[0]  # sem o "Use assim" dos alertas
        raise ConversorError(f"{mensagem}\n\n{USO}") from None


def interpretar(palavras: list[str]) -> Pedido:
    """["100", "usd"] -> 100 dólares em reais; ["500", "reais", "para", "dolar"] -> em dólares."""
    p = [sem_acento(palavra) for palavra in palavras]
    origem = None
    # O símbolo pode vir separado ("R$ 50") ou grudado no valor ("r$50", "US$10").
    if p and p[0] in ("r$", "us$"):
        origem, p = NOMES[p[0]], p[1:]
    elif p:
        simbolo = next((s for s in ("r$", "us$") if p[0].startswith(s)), None)
        if simbolo:
            origem, p = NOMES[simbolo], [p[0].removeprefix(simbolo), *p[1:]]
    if not p:
        raise ConversorError(USO)

    resto = p[1:]
    if origem is None:
        if not resto or resto[0] not in NOMES:
            raise ConversorError(USO)
        origem, resto = NOMES[resto[0]], resto[1:]
    valor = ler_quantia(p[0], ponto_decimal=origem is BITCOINS)
    if arredondar(valor, origem.casas) == 0:
        raise ConversorError(f"Esse valor é pequeno demais: o mínimo é {formatar_valor(origem, menor(origem))}.")
    if resto and resto[0] in LIGACOES:
        resto = resto[1:]
        if not resto:  # "100 usd para": faltou dizer para qual moeda
            raise ConversorError(USO)

    if not resto:
        # Sem destino: moeda estrangeira vira real; real vira dólar e bitcoin.
        destinos = (DOLARES, BITCOINS) if origem is REAL else (REAL,)
    elif len(resto) == 1 and resto[0] in NOMES:
        destinos = (NOMES[resto[0]],)
    else:
        raise ConversorError(USO)
    if destinos == (origem,):
        raise ConversorError("A moeda de origem e a de destino são a mesma.")
    return Pedido(valor, origem, destinos)


def menor(unidade: Unidade) -> Decimal:
    """O menor valor que aparece na moeda: R$ 0,01, ₿ 0,00000001."""
    return Decimal(1).scaleb(-unidade.casas)


def moedas_necessarias(pedido: Pedido) -> list[Moeda]:
    """As cotações que precisam ser buscadas (o real não precisa)."""
    unidades = [pedido.origem, *pedido.destinos]
    return list(dict.fromkeys(u.moeda for u in unidades if u.moeda is not None))


def formatar_valor(unidade: Unidade, valor: Decimal) -> str:
    """formatar_valor(DOLARES, Decimal("1234.5")) -> "US$ 1.234,50"; bitcoin sem zeros
    sobrando no fim: "₿ 0,5" em vez de "₿ 0,50000000"."""
    texto = f"{arredondar(valor, unidade.casas):,.{unidade.casas}f}"
    if unidade.casas > 2:
        inteiro, decimais = texto.split(".")
        texto = f"{inteiro}.{decimais.rstrip('0').ljust(2, '0')}"
    return f"{unidade.simbolo} " + texto.replace(",", "_").replace(".", ",").replace("_", ".")


def converter(pedido: Pedido, precos: dict[str, Decimal]) -> str:
    """precos: quanto vale 1 unidade em reais, por par ("USD-BRL": 5.17)."""

    def em_reais(unidade: Unidade) -> Decimal:
        return Decimal(1) if unidade.moeda is None else precos[unidade.moeda.par]

    if any(precos[moeda.par] <= 0 for moeda in moedas_necessarias(pedido)):
        raise ConversorError("A API de cotações devolveu um preço inválido. Tente mais tarde.")
    total = pedido.valor * em_reais(pedido.origem)
    resultados = []
    for destino in pedido.destinos:
        valor = total / em_reais(destino)
        if arredondar(valor, destino.casas) == 0:  # "R$ 0,01 em dólar" daria "US$ 0,00"
            resultados.append(f"menos de {formatar_valor(destino, menor(destino))}")
        else:
            resultados.append(formatar_valor(destino, valor))
    cotacoes = [
        f"1 {moeda.par[:3]} = {reais(precos[moeda.par], moeda.casas)}"  # como no /dolar e no /bitcoin
        for moeda in moedas_necessarias(pedido)
    ]
    rotulo = "Cotação" if len(cotacoes) == 1 else "Cotações"
    return (
        f"💱 {formatar_valor(pedido.origem, pedido.valor)} = " + " = ".join(resultados)
        + f"\n{rotulo}: " + " · ".join(cotacoes)
    )

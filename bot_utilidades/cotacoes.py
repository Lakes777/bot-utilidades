"""Cotações de moedas pela AwesomeAPI (gratuita, sem chave).

Não depende do Telegram: recebe um par como "BTC-BRL" e devolve texto pronto.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

import httpx

URL = "https://economia.awesomeapi.com.br/json/last/{par}"


@dataclass(frozen=True)
class Moeda:
    par: str  # como a API chama, ex.: "BTC-BRL"
    nome: str
    casas: int  # casas decimais ao mostrar o preço


BITCOIN = Moeda("BTC-BRL", "Bitcoin", 2)
DOLAR = Moeda("USD-BRL", "Dólar", 4)


@dataclass(frozen=True)
class Cotacao:
    moeda: Moeda
    preco: Decimal
    maxima: Decimal
    minima: Decimal
    variacao: Decimal  # em %, ex.: Decimal("-1.185")
    atualizado: datetime


class CotacaoError(Exception):
    """A API falhou ou respondeu algo inesperado; a mensagem vai para o usuário."""


def ler_resposta(moeda: Moeda, dados: dict) -> Cotacao:
    """Converte o JSON da API em Cotacao. A chave é o par sem hífen: "BTCBRL"."""
    try:
        item = dados[moeda.par.replace("-", "")]
        return Cotacao(
            moeda=moeda,
            preco=Decimal(item["bid"]),
            maxima=Decimal(item["high"]),
            minima=Decimal(item["low"]),
            variacao=Decimal(item["pctChange"]),
            atualizado=datetime.strptime(item["create_date"], "%Y-%m-%d %H:%M:%S"),
        )
    except (KeyError, TypeError, ArithmeticError, ValueError) as erro:
        raise CotacaoError("A API de cotações respondeu num formato inesperado.") from erro


async def buscar(moeda: Moeda, cliente: httpx.AsyncClient) -> Cotacao:
    try:
        resposta = await cliente.get(URL.format(par=moeda.par), timeout=10)
        resposta.raise_for_status()
    except httpx.HTTPStatusError as erro:
        if erro.response.status_code == 429:
            raise CotacaoError("Muitas consultas seguidas. Tente de novo em um minuto.") from erro
        raise CotacaoError("A API de cotações está fora do ar. Tente mais tarde.") from erro
    except httpx.HTTPError as erro:
        raise CotacaoError("Não consegui acessar a API de cotações. Tente mais tarde.") from erro
    return ler_resposta(moeda, resposta.json())


def arredondar(valor: Decimal, casas: int) -> Decimal:
    """Arredonda como na escola (1,185 -> 1,19). O padrão do Decimal daria 1,18."""
    return valor.quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)


def reais(valor: Decimal, casas: int) -> str:
    """Formato brasileiro: reais(Decimal("433082"), 2) -> "R$ 433.082,00"."""
    texto = f"{arredondar(valor, casas):,.{casas}f}"  # "433,082.00" (formato americano)
    return "R$ " + texto.replace(",", "_").replace(".", ",").replace("_", ".")


def formatar(cotacao: Cotacao) -> str:
    c = cotacao
    seta = "📈" if c.variacao >= 0 else "📉"
    variacao = f"{arredondar(c.variacao, 2):+.2f}".replace(".", ",")
    return (
        f"{c.moeda.nome}: {reais(c.preco, c.moeda.casas)}\n"
        f"{seta} Variação no dia: {variacao}%\n"
        f"Máxima: {reais(c.maxima, c.moeda.casas)}\n"
        f"Mínima: {reais(c.minima, c.moeda.casas)}\n"
        f"Atualizado em {c.atualizado:%d/%m/%Y às %H:%M}"
    )

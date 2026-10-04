import re
from decimal import Decimal

import pytest

from bot_utilidades.conversor import (
    BITCOINS,
    DOLARES,
    REAL,
    ConversorError,
    Pedido,
    converter,
    formatar_valor,
    interpretar,
    ler_quantia,
    moedas_necessarias,
)
from bot_utilidades.cotacoes import BITCOIN, DOLAR

PRECOS = {"USD-BRL": Decimal("5.1723"), "BTC-BRL": Decimal("433082")}


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("100 usd", Pedido(Decimal("100"), DOLARES, (REAL,))),
        ("100 Dólares", Pedido(Decimal("100"), DOLARES, (REAL,))),
        ("0,5 btc", Pedido(Decimal("0.5"), BITCOINS, (REAL,))),
        ("0.005 bitcoin", Pedido(Decimal("0.005"), BITCOINS, (REAL,))),
        ("1.000 dolares", Pedido(Decimal("1000"), DOLARES, (REAL,))),
        ("500 reais para dolar", Pedido(Decimal("500"), REAL, (DOLARES,))),
        ("500 reais pra btc", Pedido(Decimal("500"), REAL, (BITCOINS,))),
        ("500 reais", Pedido(Decimal("500"), REAL, (DOLARES, BITCOINS))),
        ("R$ 50 em btc", Pedido(Decimal("50"), REAL, (BITCOINS,))),
        ("r$50", Pedido(Decimal("50"), REAL, (DOLARES, BITCOINS))),
        ("US$10", Pedido(Decimal("10"), DOLARES, (REAL,))),
        ("100 usd em btc", Pedido(Decimal("100"), DOLARES, (BITCOINS,))),
        ("100 usd -> brl", Pedido(Decimal("100"), DOLARES, (REAL,))),
    ],
)
def test_interpreta(texto, esperado):
    assert interpretar(texto.split()) == esperado


@pytest.mark.parametrize("texto", ["", "100", "100 xyz", "usd 100", "100 usd para", "100 usd em btc e brl", "R$"])
def test_pedido_incompleto_mostra_como_usar(texto):
    with pytest.raises(ConversorError, match="Use assim:\n/converter"):
        interpretar(texto.split())


@pytest.mark.parametrize("texto", ["abc usd", "1e5 usd", "-5 usd"])
def test_valor_invalido(texto):
    with pytest.raises(ConversorError, match="Não entendi o valor"):
        interpretar(texto.split())


@pytest.mark.parametrize("texto", ["0 usd", "0.0 btc"])
def test_valor_zero(texto):
    with pytest.raises(ConversorError, match="maior que zero"):
        interpretar(texto.split())


@pytest.mark.parametrize("texto", ["100 usd em dolar", "100 usd usd", "R$ 50 reais"])
def test_mesma_moeda(texto):
    with pytest.raises(ConversorError, match="a mesma"):
        interpretar(texto.split())


@pytest.mark.parametrize(
    ("texto", "minimo"),
    [("0.000000001 btc", "₿ 0,00000001"), ("0,001 reais em btc", "R$ 0,01"), ("0,001 usd", "US$ 0,01")],
)
def test_valor_pequeno_demais(texto, minimo):
    with pytest.raises(ConversorError, match=f"pequeno demais: o mínimo é {re.escape(minimo)}"):
        interpretar(texto.split())


def test_resultado_pequeno_demais_vira_menos_de():
    assert converter(interpretar("0,01 reais em dolar".split()), PRECOS).startswith(
        "💱 R$ 0,01 = menos de US$ 0,01"
    )


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("1.005 btc", Decimal("1.005")), ("0.005 btc", Decimal("0.005")), ("1.005 usd", Decimal("1005")),
     ("1.000.000 reais", Decimal("1000000"))],
)
def test_ponto_no_bitcoin_e_decimal(texto, esperado):
    assert interpretar(texto.split()).valor == esperado


def test_varios_pontos_comecando_com_zero():
    with pytest.raises(ConversorError, match="Não entendi o valor"):
        interpretar("0.5.1 btc".split())


def test_valor_no_limite():
    texto = converter(interpretar("999999999999 usd em btc".split()), PRECOS)
    assert texto.startswith("💱 US$ 999.999.999.999,00 = ₿ 11.943.003,86530686")


def test_preco_zero_da_api():
    with pytest.raises(ConversorError, match="preço inválido"):
        converter(interpretar("100 usd".split()), {"USD-BRL": Decimal(0)})


def test_erro_do_valor_nao_mostra_o_uso_dos_alertas():
    with pytest.raises(ConversorError) as erro:
        interpretar("abc usd".split())
    assert "/alerta" not in str(erro.value)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("0.005", Decimal("0.005")), ("0,005", Decimal("0.005")), ("400.000", Decimal("400000")),
     ("5,20", Decimal("5.20"))],
)
def test_le_quantias(texto, esperado):
    assert ler_quantia(texto) == esperado


def test_moedas_necessarias():
    assert moedas_necessarias(Pedido(Decimal(1), REAL, (DOLARES, BITCOINS))) == [DOLAR, BITCOIN]
    assert moedas_necessarias(Pedido(Decimal(1), DOLARES, (REAL,))) == [DOLAR]


@pytest.mark.parametrize(
    ("unidade", "valor", "esperado"),
    [
        (REAL, Decimal("1234.565"), "R$ 1.234,57"),
        (DOLARES, Decimal("96.6688"), "US$ 96,67"),
        (BITCOINS, Decimal("0.5"), "₿ 0,50"),
        (BITCOINS, Decimal("0.001154523"), "₿ 0,00115452"),
        (BITCOINS, Decimal("12"), "₿ 12,00"),
    ],
)
def test_formata_valores(unidade, valor, esperado):
    assert formatar_valor(unidade, valor) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("100 usd", "💱 US$ 100,00 = R$ 517,23\nCotação: 1 USD = R$ 5,1723"),
        ("0,5 btc", "💱 ₿ 0,50 = R$ 216.541,00\nCotação: 1 BTC = R$ 433.082,00"),
        ("500 reais",
         "💱 R$ 500,00 = US$ 96,67 = ₿ 0,00115452\n"
         "Cotações: 1 USD = R$ 5,1723 · 1 BTC = R$ 433.082,00"),
        ("100 usd em btc",
         "💱 US$ 100,00 = ₿ 0,0011943\nCotações: 1 USD = R$ 5,1723 · 1 BTC = R$ 433.082,00"),
    ],
)
def test_converte(texto, esperado):
    assert converter(interpretar(texto.split()), PRECOS) == esperado

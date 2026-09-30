from decimal import Decimal

import pytest

from bot_utilidades.alertas import (
    ABAIXO,
    ACIMA,
    AlertaError,
    atingiu,
    aviso,
    interpretar,
    ler_valor,
    longe_demais,
)
from bot_utilidades.cotacoes import BITCOIN, DOLAR


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("400000", "400000"),
        ("400.000", "400000"),
        ("400.000,50", "400000.50"),
        ("1.234.567", "1234567"),
        ("5,20", "5.20"),
        ("5.20", "5.20"),
        ("5.2", "5.2"),
        ("R$5,20", "5.20"),
    ],
)
def test_ler_valor(texto, esperado):
    assert ler_valor(texto) == Decimal(esperado)


@pytest.mark.parametrize(
    "texto", ["abc", "0", "-5", "NaN", "Infinity", "5,2,0", "1e30", "4e5", "9" * 30, "1.000.000.000.000"]
)
def test_ler_valor_recusa(texto):
    with pytest.raises(AlertaError):
        ler_valor(texto)


def test_interpretar():
    assert interpretar(["Bitcoin", "acima", "400.000"]) == (
        interpretar(["btc", ">", "400000"])
    )
    pedido = interpretar(["dólar", "ABAIXO", "R$", "5,20"])
    assert (pedido.moeda, pedido.direcao, pedido.valor) == (DOLAR, ABAIXO, Decimal("5.20"))


@pytest.mark.parametrize(
    "args, trecho",
    [
        ([], "Use assim"),
        (["bitcoin", "acima"], "Use assim"),
        (["euro", "acima", "6"], "Não conheço a moeda 'euro'"),
        (["bitcoin", "perto", "6"], "Use acima ou abaixo"),
        (["bitcoin", "acima", "muito"], "Não entendi o valor"),
    ],
)
def test_interpretar_com_erro(args, trecho):
    with pytest.raises(AlertaError, match=trecho):
        interpretar(args)


def test_atingiu_conta_o_valor_exato():
    assert atingiu(ACIMA, Decimal("400000"), Decimal("400000"))
    assert atingiu(ACIMA, Decimal("400000"), Decimal("400000.01"))
    assert not atingiu(ACIMA, Decimal("400000"), Decimal("399999.99"))
    assert atingiu(ABAIXO, Decimal("5.20"), Decimal("5.20"))
    assert not atingiu(ABAIXO, Decimal("5.20"), Decimal("5.2001"))


def test_longe_demais():
    preco = Decimal("5.17")
    assert longe_demais(Decimal("5200"), preco)  # "5.200" no dólar
    assert longe_demais(Decimal("0.4"), preco)
    assert not longe_demais(Decimal("5.50"), preco)
    assert not longe_demais(Decimal("51"), preco)


def test_mesmo_preco_dispara_abaixo_e_nao_acima():
    preco = Decimal("420000")
    assert atingiu(ABAIXO, Decimal("450000"), preco)
    assert not atingiu(ACIMA, Decimal("450000"), preco)


def test_aviso():
    assert aviso(BITCOIN, ACIMA, Decimal("400000"), Decimal("401234.5")) == (
        "🔔 Alerta: Bitcoin acima de R$ 400.000,00\nAgora está em R$ 401.234,50."
    )

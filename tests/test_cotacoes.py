import asyncio
from decimal import Decimal

import httpx
import pytest

from bot_utilidades.cotacoes import (
    BITCOIN,
    DOLAR,
    CotacaoError,
    buscar,
    formatar,
    ler_resposta,
    reais,
)

# Resposta real da AwesomeAPI, copiada em 24/09/2026.
RESPOSTA_BTC = {
    "BTCBRL": {
        "code": "BTC", "codein": "BRL", "name": "Bitcoin/Real Brasileiro",
        "high": "442235", "low": "430000", "varBid": "-5192", "pctChange": "-1.185",
        "bid": "433082", "ask": "433083", "timestamp": "1790249964",
        "create_date": "2026-09-24 08:39:24",
    }
}


def buscar_com_api_falsa(moeda, responder):
    """Roda buscar() com um servidor falso: nenhuma requisição sai pra internet."""
    async def rodar():
        async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as cliente:
            return await buscar(moeda, cliente)
    return asyncio.run(rodar())


@pytest.mark.parametrize(
    ("valor", "casas", "esperado"),
    [
        (Decimal("433082"), 2, "R$ 433.082,00"),
        (Decimal("5.1679"), 4, "R$ 5,1679"),
        (Decimal("1234567.891"), 2, "R$ 1.234.567,89"),
    ],
)
def test_reais_usa_formato_brasileiro(valor, casas, esperado):
    assert reais(valor, casas) == esperado


def test_le_resposta_da_api():
    cotacao = ler_resposta(BITCOIN, RESPOSTA_BTC)
    assert cotacao.preco == Decimal("433082")
    assert cotacao.variacao == Decimal("-1.185")
    assert cotacao.atualizado.hour == 8


def test_formata_mensagem():
    texto = formatar(ler_resposta(BITCOIN, RESPOSTA_BTC))
    assert texto.startswith("Bitcoin: R$ 433.082,00")
    assert "📉 Variação no dia: -1,19%" in texto
    assert "Atualizado em 24/09/2026 às 08:39" in texto


def test_variacao_positiva_mostra_sinal_de_mais():
    dados = {"USDBRL": {**RESPOSTA_BTC["BTCBRL"], "pctChange": "0.0735"}}
    assert "📈 Variação no dia: +0,07%" in formatar(ler_resposta(DOLAR, dados))


def test_resposta_sem_o_par_pedido():
    with pytest.raises(CotacaoError, match="formato inesperado"):
        ler_resposta(DOLAR, RESPOSTA_BTC)


def test_busca_o_par_certo_na_url():
    urls = []

    def responder(request):
        urls.append(str(request.url))
        return httpx.Response(200, json=RESPOSTA_BTC)

    cotacao = buscar_com_api_falsa(BITCOIN, responder)
    assert urls == ["https://economia.awesomeapi.com.br/json/last/BTC-BRL"]
    assert cotacao.preco == Decimal("433082")


@pytest.mark.parametrize(
    ("status", "mensagem"),
    [(429, "Muitas consultas"), (500, "fora do ar")],
)
def test_erros_http_viram_mensagem_amigavel(status, mensagem):
    with pytest.raises(CotacaoError, match=mensagem):
        buscar_com_api_falsa(BITCOIN, lambda request: httpx.Response(status))


def test_sem_internet():
    def responder(request):
        raise httpx.ConnectError("sem rede")

    with pytest.raises(CotacaoError, match="Não consegui acessar"):
        buscar_com_api_falsa(BITCOIN, responder)

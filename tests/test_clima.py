import asyncio

import httpx
import pytest

from bot_utilidades.clima import (
    Cidade,
    ClimaError,
    buscar,
    formatar,
    graus,
    ler_cidade,
    ler_clima,
)

# Respostas reais do Open-Meteo, copiadas (e resumidas) em 24/09/2026.
RESPOSTA_BUSCA = {
    "results": [{
        "id": 3464975, "name": "Curitiba", "latitude": -25.42778, "longitude": -49.27306,
        "country_code": "BR", "country": "Brasil", "admin1": "Paraná",
    }]
}
RESPOSTA_PREVISAO = {
    "current": {
        "time": "2026-09-24T20:30", "temperature_2m": 14.0, "apparent_temperature": 13.9,
        "relative_humidity_2m": 97, "weather_code": 3, "wind_speed_10m": 8.1,
    },
    "daily": {
        "time": ["2026-09-24"], "temperature_2m_max": [19.2],
        "temperature_2m_min": [10.1], "precipitation_probability_max": [0],
    },
}
CURITIBA = ler_cidade(RESPOSTA_BUSCA, "Curitiba")


def buscar_com_api_falsa(nome, responder):
    """Roda buscar() com um servidor falso: nenhuma requisição sai pra internet."""
    async def rodar():
        async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as cliente:
            return await buscar(nome, cliente)
    return asyncio.run(rodar())


def api_falsa(request):
    if request.url.host.startswith("geocoding"):
        return httpx.Response(200, json=RESPOSTA_BUSCA)
    return httpx.Response(200, json=RESPOSTA_PREVISAO)


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [(14.0, "14°C"), (13.9, "14°C"), (2.5, "3°C"), (-0.4, "0°C"), (-3.6, "-4°C")],
)
def test_graus_arredonda_como_na_escola(valor, esperado):
    assert graus(valor) == esperado


def test_le_cidade():
    assert CURITIBA == Cidade("Curitiba", "Paraná", "Brasil", -25.42778, -49.27306)


def test_cidade_sem_estado():
    dados = {"results": [{"name": "Mônaco", "latitude": 43.7, "longitude": 7.4, "country": "Mônaco"}]}
    assert ler_cidade(dados, "Monaco").regiao == ""


def test_cidade_nao_encontrada():
    # A API responde sem a chave "results" quando não acha nada.
    with pytest.raises(ClimaError, match='Não encontrei a cidade "Xyzópolis"'):
        ler_cidade({"generationtime_ms": 0.09}, "Xyzópolis")


def test_formata_mensagem():
    texto = formatar(ler_clima(CURITIBA, RESPOSTA_PREVISAO))
    assert texto.splitlines() == [
        "📍 Curitiba, Paraná, Brasil",
        "☁️ Nublado",
        "Agora: 14°C (sensação de 14°C)",
        "Hoje: mínima de 10°C e máxima de 19°C",
        "💧 Umidade: 97%",
        "💨 Vento: 8 km/h",
        "☔ Chance de chuva hoje: 0%",
    ]


def test_sem_chance_de_chuva_omite_a_linha():
    dados = {**RESPOSTA_PREVISAO, "daily": {**RESPOSTA_PREVISAO["daily"], "precipitation_probability_max": [None]}}
    assert "Chance de chuva" not in formatar(ler_clima(CURITIBA, dados))


def test_codigo_desconhecido():
    dados = {**RESPOSTA_PREVISAO, "current": {**RESPOSTA_PREVISAO["current"], "weather_code": 42}}
    assert "Condição desconhecida" in formatar(ler_clima(CURITIBA, dados))


def test_previsao_em_formato_inesperado():
    with pytest.raises(ClimaError, match="formato inesperado"):
        ler_clima(CURITIBA, {"current": {}})


def test_busca_cidade_e_depois_previsao_com_as_coordenadas():
    pedidos = []

    def responder(request):
        pedidos.append(request.url)
        return api_falsa(request)

    clima = buscar_com_api_falsa("Curitiba", responder)
    busca, previsao = pedidos
    assert busca.params["name"] == "Curitiba"
    assert previsao.params["latitude"] == "-25.42778"
    assert previsao.params["longitude"] == "-49.27306"
    assert clima.temperatura == 14.0


def test_cidade_nao_encontrada_nao_pede_previsao():
    pedidos = []

    def responder(request):
        pedidos.append(request.url)
        return httpx.Response(200, json={"generationtime_ms": 0.09})

    with pytest.raises(ClimaError, match="Não encontrei"):
        buscar_com_api_falsa("Xyzópolis", responder)
    assert len(pedidos) == 1


@pytest.mark.parametrize(
    ("status", "mensagem"),
    [(429, "Muitas consultas"), (500, "fora do ar")],
)
def test_erros_http_viram_mensagem_amigavel(status, mensagem):
    with pytest.raises(ClimaError, match=mensagem):
        buscar_com_api_falsa("Curitiba", lambda request: httpx.Response(status))


def test_sem_internet():
    def responder(request):
        raise httpx.ConnectError("sem rede")

    with pytest.raises(ClimaError, match="Não consegui acessar"):
        buscar_com_api_falsa("Curitiba", responder)

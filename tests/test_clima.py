import asyncio

import httpx
import pytest

from bot_utilidades.clima import (
    Cidade,
    ClimaError,
    aviso_de_chuva,
    buscar,
    buscar_chuva,
    faixas,
    ler_chuva_por_hora,
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


# ---------- Aviso de chuva ----------

def previsao_por_hora(chances):
    return {
        "hourly": {
            "time": [f"2026-10-04T{hora:02d}:00" for hora in range(len(chances))],
            "precipitation_probability": chances,
        }
    }


def test_le_a_chuva_hora_a_hora():
    assert ler_chuva_por_hora(previsao_por_hora([10, 80, None])) == [(0, 10), (1, 80)]


@pytest.mark.parametrize("dados", [{}, {"hourly": {}}, {"hourly": {"time": ["x"], "precipitation_probability": [1]}},
                                   {"hourly": {"time": ["2026-10-04T01:00"], "precipitation_probability": []}}])
def test_chuva_em_formato_inesperado(dados):
    with pytest.raises(ClimaError, match="formato inesperado"):
        ler_chuva_por_hora(dados)


@pytest.mark.parametrize(
    ("horas", "esperado"),
    [
        ([14], "às 14h"),
        ([14, 15, 16], "das 14h às 17h"),
        ([16, 14, 15, 20], "das 14h às 17h e às 20h"),
        ([8, 12, 13, 22, 23], "às 8h, das 12h às 14h e das 22h às 0h"),
    ],
)
def test_faixas_de_horas(horas, esperado):
    assert faixas(horas) == esperado


def test_aviso_de_chuva():
    chuva = [(hora, 80 if hora in (14, 15) else 70 if hora == 20 else 10) for hora in range(24)]
    assert aviso_de_chuva(CURITIBA, chuva, a_partir_de=7) == (
        "☔ Vai chover hoje em Curitiba, Paraná: até 80% de chance, das 14h às 16h e às 20h. "
        "Leve o guarda-chuva!"
    )


def test_sem_chuva_nao_tem_aviso():
    assert aviso_de_chuva(CURITIBA, [(hora, 49) for hora in range(24)], a_partir_de=0) is None


def test_chuva_que_ja_passou_nao_conta():
    chuva = [(hora, 90 if hora == 5 else 0) for hora in range(24)]
    assert aviso_de_chuva(CURITIBA, chuva, a_partir_de=7) is None
    assert aviso_de_chuva(CURITIBA, chuva, a_partir_de=5) is not None


def test_busca_a_chuva_no_horario_de_brasilia():
    pedidos = []

    def responder(request):
        pedidos.append(request)
        return httpx.Response(200, json=previsao_por_hora([0] * 23 + [60]))

    async def rodar():
        async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as cliente:
            return await buscar_chuva(CURITIBA, cliente)

    chuva = asyncio.run(rodar())
    assert chuva[-1] == (23, 60)
    [pedido] = pedidos
    assert pedido.url.params["timezone"] == "America/Sao_Paulo"
    assert pedido.url.params["hourly"] == "precipitation_probability"

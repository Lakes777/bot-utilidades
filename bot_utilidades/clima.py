"""Clima atual pelo Open-Meteo (gratuito, sem chave).

São duas consultas: a geocodificação transforma o nome da cidade em
latitude/longitude, e a previsão usa essas coordenadas.
Não depende do Telegram.
"""

import math
from dataclasses import dataclass

import httpx

URL_BUSCA = "https://geocoding-api.open-meteo.com/v1/search"
URL_PREVISAO = "https://api.open-meteo.com/v1/forecast"

# Códigos de tempo da OMM usados pelo Open-Meteo.
# https://open-meteo.com/en/docs (seção "WMO Weather interpretation codes")
CONDICOES = {
    0: "☀️ Céu limpo",
    1: "🌤️ Poucas nuvens",
    2: "⛅ Parcialmente nublado",
    3: "☁️ Nublado",
    45: "🌫️ Neblina",
    48: "🌫️ Neblina com geada",
    51: "🌦️ Garoa fraca",
    53: "🌦️ Garoa",
    55: "🌦️ Garoa forte",
    56: "🌧️ Garoa congelante",
    57: "🌧️ Garoa congelante forte",
    61: "🌧️ Chuva fraca",
    63: "🌧️ Chuva",
    65: "🌧️ Chuva forte",
    66: "🌧️ Chuva congelante",
    67: "🌧️ Chuva congelante forte",
    71: "🌨️ Neve fraca",
    73: "🌨️ Neve",
    75: "🌨️ Neve forte",
    77: "🌨️ Grãos de neve",
    80: "🌦️ Pancadas de chuva fracas",
    81: "🌦️ Pancadas de chuva",
    82: "⛈️ Pancadas de chuva fortes",
    85: "🌨️ Pancadas de neve",
    86: "🌨️ Pancadas de neve fortes",
    95: "⛈️ Trovoada",
    96: "⛈️ Trovoada com granizo",
    99: "⛈️ Trovoada com granizo forte",
}


@dataclass(frozen=True)
class Cidade:
    nome: str
    regiao: str  # estado/província, ex.: "Paraná" (pode vir vazio)
    pais: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Clima:
    cidade: Cidade
    temperatura: float
    sensacao: float
    umidade: int
    vento: float  # km/h
    codigo: int
    maxima: float
    minima: float
    chance_chuva: int | None  # % no dia; a API às vezes não tem esse dado


class ClimaError(Exception):
    """Cidade não encontrada ou API com problema; a mensagem vai para o usuário."""


async def _get_json(cliente: httpx.AsyncClient, url: str, params: dict) -> dict:
    try:
        resposta = await cliente.get(url, params=params, timeout=10)
        resposta.raise_for_status()
    except httpx.HTTPStatusError as erro:
        if erro.response.status_code == 429:
            raise ClimaError("Muitas consultas seguidas. Tente de novo em um minuto.") from erro
        raise ClimaError("A API de clima está fora do ar. Tente mais tarde.") from erro
    except httpx.HTTPError as erro:
        raise ClimaError("Não consegui acessar a API de clima. Tente mais tarde.") from erro
    return resposta.json()


def ler_cidade(dados: dict, busca: str) -> Cidade:
    resultados = dados.get("results")
    if not resultados:
        raise ClimaError(f'Não encontrei a cidade "{busca}". Confira o nome.')
    r = resultados[0]  # a API já ordena pelo mais relevante
    return Cidade(r["name"], r.get("admin1", ""), r.get("country", ""), r["latitude"], r["longitude"])


def ler_clima(cidade: Cidade, dados: dict) -> Clima:
    try:
        agora, dia = dados["current"], dados["daily"]
        return Clima(
            cidade=cidade,
            temperatura=agora["temperature_2m"],
            sensacao=agora["apparent_temperature"],
            umidade=agora["relative_humidity_2m"],
            vento=agora["wind_speed_10m"],
            codigo=agora["weather_code"],
            maxima=dia["temperature_2m_max"][0],
            minima=dia["temperature_2m_min"][0],
            chance_chuva=dia["precipitation_probability_max"][0],
        )
    except (KeyError, IndexError, TypeError) as erro:
        raise ClimaError("A API de clima respondeu num formato inesperado.") from erro


async def buscar_cidade(nome: str, cliente: httpx.AsyncClient) -> Cidade:
    busca = await _get_json(cliente, URL_BUSCA, {"name": nome, "count": 1, "language": "pt"})
    return ler_cidade(busca, nome)


async def buscar(nome: str, cliente: httpx.AsyncClient) -> Clima:
    cidade = await buscar_cidade(nome, cliente)
    previsao = await _get_json(cliente, URL_PREVISAO, {
        "latitude": cidade.latitude,
        "longitude": cidade.longitude,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto",
        "forecast_days": 1,
    })
    return ler_clima(cidade, previsao)


def arredondar(valor: float) -> int:
    """Arredonda como na escola (2,5 -> 3). O round() do Python daria 2."""
    return math.floor(valor + 0.5)


def graus(valor: float) -> str:
    return f"{arredondar(valor)}°C"


def formatar(clima: Clima) -> str:
    c = clima
    local = ", ".join(parte for parte in (c.cidade.nome, c.cidade.regiao, c.cidade.pais) if parte)
    linhas = [
        f"📍 {local}",
        CONDICOES.get(c.codigo, "🌡️ Condição desconhecida"),
        f"Agora: {graus(c.temperatura)} (sensação de {graus(c.sensacao)})",
        f"Hoje: mínima de {graus(c.minima)} e máxima de {graus(c.maxima)}",
        f"💧 Umidade: {c.umidade}%",
        f"💨 Vento: {arredondar(c.vento)} km/h",
    ]
    if c.chance_chuva is not None:
        linhas.append(f"☔ Chance de chuva hoje: {c.chance_chuva}%")
    return "\n".join(linhas)


# ---------- Aviso de chuva ----------

# Chance (%) a partir da qual uma hora conta como "vai chover".
CHANCE_MINIMA = 50


def nome_completo(cidade: Cidade) -> str:
    """"Curitiba, Paraná" (sem o país, que quase sempre é o Brasil)."""
    return ", ".join(parte for parte in (cidade.nome, cidade.regiao) if parte)


def ler_chuva_por_hora(dados: dict) -> list[tuple[int, int]]:
    """A previsão do dia, hora a hora: [(0, 10), (1, 5), ..., (23, 80)] -> (hora, chance %)."""
    try:
        horas, chances = dados["hourly"]["time"], dados["hourly"]["precipitation_probability"]
        return [
            (int(momento[11:13]), chance)  # "2026-10-04T14:00" -> 14
            for momento, chance in zip(horas, chances, strict=True)
            if chance is not None
        ]
    except (KeyError, TypeError, ValueError) as erro:
        raise ClimaError("A API de clima respondeu num formato inesperado.") from erro


async def buscar_chuva(cidade: Cidade, cliente: httpx.AsyncClient) -> list[tuple[int, int]]:
    """A chance de chuva de cada hora de hoje (horário de Brasília)."""
    previsao = await _get_json(cliente, URL_PREVISAO, {
        "latitude": cidade.latitude,
        "longitude": cidade.longitude,
        "hourly": "precipitation_probability",
        # Horas no relógio de Brasília, o mesmo dos lembretes e do horário do aviso.
        "timezone": "America/Sao_Paulo",
        "forecast_days": 1,
    })
    return ler_chuva_por_hora(previsao)


def faixas(horas: list[int]) -> str:
    """[14, 15, 16, 20] -> "das 14h às 17h e às 20h" (horas seguidas viram uma faixa)."""
    grupos: list[list[int]] = []
    for hora in sorted(horas):
        if grupos and hora == grupos[-1][-1] + 1:
            grupos[-1].append(hora)
        else:
            grupos.append([hora])
    partes = [
        f"às {g[0]}h" if len(g) == 1 else f"das {g[0]}h às {(g[-1] + 1) % 24}h" for g in grupos
    ]
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]


def aviso_de_chuva(cidade: Cidade, chuva: list[tuple[int, int]], a_partir_de: int) -> str | None:
    """A mensagem do aviso, ou None se não houver chuva provável daqui até o fim do dia."""
    provaveis = [(hora, chance) for hora, chance in chuva if hora >= a_partir_de and chance >= CHANCE_MINIMA]
    if not provaveis:
        return None
    maior = max(chance for _, chance in provaveis)
    return (
        f"☔ Vai chover hoje em {nome_completo(cidade)}: até {maior}% de chance, "
        f"{faixas([hora for hora, _ in provaveis])}. Leve o guarda-chuva!"
    )

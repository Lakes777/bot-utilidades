"""Lê os prazos (provas, trabalhos, avaliações) do Coursebook, o painel de estudos
do mesmo autor, pela rota somente leitura GET /api/prazos, com uma chave de acesso.

Não depende do Telegram: quem chama e responde é o bot.
"""

from dataclasses import dataclass
from datetime import date

import httpx

# Quantos dias o /prazos mostra quando não se diz nada, e o máximo que a API aceita.
DIAS_PADRAO = 7
DIAS_MAXIMOS = 60

# O aviso diário fala só do que está bem perto: hoje, amanhã e depois de amanhã.
DIAS_DO_AVISO = 2

# A Vercel pode levar alguns segundos para acordar o servidor no primeiro pedido.
TEMPO_MAXIMO = 20

DIAS_DA_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

USO = (
    "Use assim:\n"
    "/prazos (o que vence nos próximos 7 dias)\n"
    "/prazos 14 (nos próximos 14 dias)\n"
    "/prazos avisar 19:00 (todo dia, aviso do que vence até depois de amanhã)\n"
    "/prazos parar (desliga o aviso)"
)


class CoursebookError(Exception):
    """Erro da API ou pedido inválido; a mensagem vai para o usuário."""


@dataclass(frozen=True)
class Prazo:
    data: date
    dias_restantes: int
    tipo: str  # "Prova", "Trabalho", "Apresentação", "Avaliação"
    titulo: str
    materia: str | None
    hora_aula: str | None  # "19:00": começo da aula da matéria naquele dia


def ler_dias(palavras: list[str]) -> int:
    """[] -> 7; ["14"] -> 14."""
    if not palavras:
        return DIAS_PADRAO
    if len(palavras) != 1 or not palavras[0].isdecimal() or not 1 <= int(palavras[0]) <= DIAS_MAXIMOS:
        raise CoursebookError(f"Diga quantos dias, de 1 a {DIAS_MAXIMOS}.\n{USO}")
    return int(palavras[0])


def ler_prazos(dados: dict) -> list[Prazo]:
    try:
        prazos = [
            Prazo(
                date.fromisoformat(item["data"]),
                item["diasRestantes"],
                item["tipoNome"],
                item["titulo"],
                item.get("materia"),
                item.get("horaAula"),
            )
            for item in dados["prazos"]
        ]
    except (KeyError, TypeError, ValueError) as erro:
        raise CoursebookError("O Coursebook respondeu num formato inesperado.") from erro
    # Confere os tipos aqui, para um null do servidor não derrubar a formatação depois.
    for p in prazos:
        textos_ok = isinstance(p.tipo, str) and isinstance(p.titulo, str)
        opcionais_ok = all(v is None or isinstance(v, str) for v in (p.materia, p.hora_aula))
        dias_ok = isinstance(p.dias_restantes, int) and not isinstance(p.dias_restantes, bool)
        if not (textos_ok and opcionais_ok and dias_ok):
            raise CoursebookError("O Coursebook respondeu num formato inesperado.")
    return prazos


async def buscar_prazos(url: str, chave: str, dias: int, cliente: httpx.AsyncClient) -> list[Prazo]:
    try:
        resposta = await cliente.get(
            f"{url}/api/prazos",
            params={"dias": dias},
            # Só neste pedido: a chave nunca vai para as outras APIs do bot.
            headers={"Authorization": f"Bearer {chave}"},
            timeout=TEMPO_MAXIMO,
        )
    except httpx.HTTPError as erro:
        raise CoursebookError("Não consegui acessar o Coursebook. Tente mais tarde.") from erro
    if resposta.status_code == 401:
        raise CoursebookError(
            "O Coursebook não aceitou a chave (ela foi apagada?). Crie outra na tela "
            "Dados > Chaves de acesso e troque a COURSEBOOK_CHAVE no .env do bot."
        )
    if resposta.status_code != 200:
        raise CoursebookError("O Coursebook está com problema agora. Tente mais tarde.")
    try:
        return ler_prazos(resposta.json())
    except ValueError as erro:  # não era JSON
        raise CoursebookError("O Coursebook respondeu num formato inesperado.") from erro


def quando(prazo: Prazo) -> str:
    if prazo.dias_restantes == 0:
        return "hoje"
    if prazo.dias_restantes == 1:
        return "amanhã"
    return f"em {prazo.dias_restantes} dias"


def linha(prazo: Prazo) -> str:
    """"• 06/10, terça (em 2 dias): Prova do RA1 · Física, aula às 19:00"."""
    detalhes = [parte for parte in (prazo.materia, prazo.hora_aula and f"aula às {prazo.hora_aula}") if parte]
    extra = f" · {', '.join(detalhes)}" if detalhes else ""
    titulo = prazo.titulo if prazo.tipo.lower() in prazo.titulo.lower() else f"{prazo.tipo}: {prazo.titulo}"
    dia = f"{prazo.data:%d/%m}, {DIAS_DA_SEMANA[prazo.data.weekday()]}"
    return f"• {dia} ({quando(prazo)}): {titulo}{extra}"


def formatar(prazos: list[Prazo], dias: int) -> str:
    if not prazos:
        return f"📚 Nada vencendo nos próximos {dias} dias."
    return f"📚 Prazos dos próximos {dias} dias:\n" + "\n".join(linha(p) for p in prazos)


def aviso(prazos: list[Prazo]) -> str | None:
    """O aviso diário: só o que vence até depois de amanhã; None se não houver nada."""
    perto = [p for p in prazos if p.dias_restantes <= DIAS_DO_AVISO]
    if not perto:
        return None
    return "📚 Está chegando:\n" + "\n".join(linha(p) for p in perto)

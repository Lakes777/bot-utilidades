import asyncio
from datetime import date

import httpx
import pytest

from bot_utilidades.coursebook import (
    CoursebookError,
    Prazo,
    aviso,
    buscar_prazos,
    formatar,
    ler_dias,
    ler_prazos,
    linha,
)

CHAVE = "cb_" + "d" * 43
URL = "https://coursebook.exemplo"

# Formato documentado em docs/nuvem.md do Coursebook (GET /api/prazos).
RESPOSTA = {
    "hoje": "2026-10-04", "ate": "2026-10-11", "dias": 7,
    "prazos": [
        {"data": "2026-10-04", "diasRestantes": 0, "tipo": "trabalho", "tipoNome": "Trabalho",
         "titulo": "Relatório", "materia": None, "horaAula": None},
        {"data": "2026-10-06", "diasRestantes": 2, "tipo": "prova", "tipoNome": "Prova",
         "titulo": "Prova do RA1", "materia": "Física", "horaAula": "19:00"},
        {"data": "2026-10-08", "diasRestantes": 4, "tipo": "avaliacao", "tipoNome": "Avaliação",
         "titulo": "Lista 2 (RA1)", "materia": "Cálculo", "horaAula": None},
    ],
}
PRAZOS = ler_prazos(RESPOSTA)


def test_le_os_prazos():
    assert PRAZOS[1] == Prazo(date(2026, 10, 6), 2, "Prova", "Prova do RA1", "Física", "19:00")
    assert PRAZOS[0].materia is None


@pytest.mark.parametrize("dados", [{}, {"prazos": [{"data": "x"}]}, {"prazos": None},
                                   {"prazos": [{**RESPOSTA["prazos"][0], "data": "2026-13-01"}]},
                                   {"prazos": [{**RESPOSTA["prazos"][0], "titulo": None}]},
                                   {"prazos": [{**RESPOSTA["prazos"][0], "tipoNome": 3}]},
                                   {"prazos": [{**RESPOSTA["prazos"][0], "materia": 5}]},
                                   {"prazos": [{**RESPOSTA["prazos"][0], "diasRestantes": "2"}]}])
def test_formato_inesperado(dados):
    with pytest.raises(CoursebookError, match="formato inesperado"):
        ler_prazos(dados)


@pytest.mark.parametrize(("palavras", "esperado"), [([], 7), (["14"], 14), (["1"], 1), (["60"], 60)])
def test_le_dias(palavras, esperado):
    assert ler_dias(palavras) == esperado


@pytest.mark.parametrize("palavras", [["0"], ["61"], ["sete"], ["7", "8"], ["-1"]])
def test_dias_invalidos(palavras):
    with pytest.raises(CoursebookError, match="de 1 a 60"):
        ler_dias(palavras)


def test_linhas():
    assert linha(PRAZOS[0]) == "• 04/10, domingo (hoje): Trabalho: Relatório"
    assert linha(PRAZOS[1]) == "• 06/10, terça (em 2 dias): Prova do RA1 · Física, aula às 19:00"
    assert linha(PRAZOS[2]) == "• 08/10, quinta (em 4 dias): Avaliação: Lista 2 (RA1) · Cálculo"
    amanha = Prazo(date(2026, 10, 5), 1, "Apresentação", "Seminário", "História", None)
    assert linha(amanha) == "• 05/10, segunda (amanhã): Apresentação: Seminário · História"


def test_formata_a_lista():
    assert formatar(PRAZOS, 7).startswith("📚 Prazos dos próximos 7 dias:\n• 04/10")
    assert formatar([], 14) == "📚 Nada vencendo nos próximos 14 dias."


def test_aviso_so_do_que_esta_perto():
    texto = aviso(PRAZOS)
    assert texto.startswith("📚 Está chegando:")
    assert "Relatório" in texto and "Prova do RA1" in texto and "Lista 2" not in texto
    assert aviso(PRAZOS[2:]) is None
    assert aviso([]) is None


def buscar_com_api_falsa(responder, dias=7):
    async def rodar():
        async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as cliente:
            return await buscar_prazos(URL, CHAVE, dias, cliente)
    return asyncio.run(rodar())


def test_busca_com_a_chave_no_cabecalho():
    pedidos = []

    def responder(request):
        pedidos.append(request)
        return httpx.Response(200, json=RESPOSTA)

    assert buscar_com_api_falsa(responder, dias=14) == PRAZOS
    [pedido] = pedidos
    assert str(pedido.url) == f"{URL}/api/prazos?dias=14"
    assert pedido.headers["Authorization"] == f"Bearer {CHAVE}"


@pytest.mark.parametrize(
    ("resposta", "erro"),
    [
        (httpx.Response(401, json={"erro": "Chave de acesso inválida ou apagada."}), "não aceitou a chave"),
        (httpx.Response(500), "com problema agora"),
        (httpx.Response(307, headers={"Location": "https://outro.exemplo"}), "com problema agora"),
        (httpx.Response(200, text="<html>"), "formato inesperado"),
    ],
)
def test_erros_da_api(resposta, erro):
    with pytest.raises(CoursebookError, match=erro) as excecao:
        buscar_com_api_falsa(lambda request: resposta)
    assert CHAVE not in str(excecao.value)


def test_sem_internet():
    def responder(request):
        raise httpx.ConnectError("sem rede")

    with pytest.raises(CoursebookError, match="Não consegui acessar o Coursebook"):
        buscar_com_api_falsa(responder)

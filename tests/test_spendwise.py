import asyncio
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from bot_utilidades.spendwise import Gasto, SpendwiseError, confirmar, interpretar, lancar, ler_data

HOJE = date(2026, 10, 4)
CHAVE = "sw_" + "a" * 40
URL = "https://spendwise.exemplo"


@pytest.mark.parametrize(
    ("palavras", "esperado"),
    [
        (["35", "mercado"], Gasto(Decimal("35"), "mercado", "", HOJE)),
        (["35,90", "Mercado", "pão", "e", "leite"], Gasto(Decimal("35.90"), "mercado", "pão e leite", HOJE)),
        (["1.200", "aluguel"], Gasto(Decimal("1200"), "aluguel", "", HOJE)),
        (["R$12", "lanche"], Gasto(Decimal("12"), "lanche", "", HOJE)),
        (["120", "farmácia", "ontem"], Gasto(Decimal("120"), "farmácia", "", date(2026, 10, 3))),
        (["50", "uber", "volta", "20/09"], Gasto(Decimal("50"), "uber", "volta", date(2026, 9, 20))),
        (["50", "presente", "25/12"], Gasto(Decimal("50"), "presente", "", date(2025, 12, 25))),
        (["50", "uber", "Hoje"], Gasto(Decimal("50"), "uber", "", HOJE)),
        (["10", "x", "29/02"], Gasto(Decimal("10"), "x", "", date(2024, 2, 29))),
    ],
)
def test_interpreta(palavras, esperado):
    assert interpretar(palavras, HOJE) == esperado


@pytest.mark.parametrize("palavras", [[], ["35"]])
def test_incompleto_mostra_como_usar(palavras):
    with pytest.raises(SpendwiseError, match="Use assim:\n/gasto 35 mercado"):
        interpretar(palavras, HOJE)


@pytest.mark.parametrize(
    ("palavras", "erro"),
    [
        (["abc", "mercado"], "Não entendi o valor"),
        (["0", "mercado"], "maior que zero"),
        (["3,555", "mercado"], "2 casas"),
        (["10", "x", "31/02"], "não existe"),
        (["10", "x", "05/10/2026"], "futuro"),
        (["10", "a" * 41], "categoria pode ter até 40"),
        (["10", "x", "a" * 201], "descrição pode ter até 200"),
        (["10000000000", "x"], "grande demais"),
        (["35", "ontem"], "Faltou a categoria"),
        (["35", "20/09"], "Faltou a categoria"),
    ],
)
def test_erros(palavras, erro):
    with pytest.raises(SpendwiseError, match=erro):
        interpretar(palavras, HOJE)


def test_erro_do_valor_nao_mostra_o_uso_dos_alertas():
    with pytest.raises(SpendwiseError) as erro:
        interpretar(["abc", "mercado"], HOJE)
    assert "/alerta" not in str(erro.value)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("ontem", date(2026, 10, 3)), ("anteontem", date(2026, 10, 2)), ("4/10", HOJE),
     ("20/09/2025", date(2025, 9, 20)), ("mercado", None)],
)
def test_le_datas(texto, esperado):
    assert ler_data(texto, HOJE) == esperado


def lancar_com_api_falsa(responder):
    async def rodar():
        async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as cliente:
            return await lancar(Gasto(Decimal("35.90"), "mercado", "pão", HOJE), URL, CHAVE, cliente)
    return asyncio.run(rodar())


def test_lanca_com_a_chave_no_cabecalho():
    pedidos = []

    def responder(request):
        pedidos.append(request)
        return httpx.Response(201, json={"id": 42, "valor": "35.90"})

    assert lancar_com_api_falsa(responder) == 42
    [pedido] = pedidos
    assert (pedido.method, str(pedido.url)) == ("POST", f"{URL}/gastos")
    assert pedido.headers["Authorization"] == f"Bearer {CHAVE}"
    assert json.loads(pedido.content) == {
        "valor": "35.90", "categoria": "mercado", "descricao": "pão", "data": "2026-10-04"
    }


@pytest.mark.parametrize(
    ("resposta", "erro"),
    [
        (httpx.Response(401, json={"detail": "Chave de acesso inválida ou apagada"}), "não aceitou a chave"),
        (httpx.Response(403, json={"detail": "Limite de 20.000 gastos"}), "recusou: Limite de 20.000 gastos"),
        (httpx.Response(403, text="nada"), "recusou: sem detalhes"),
        (httpx.Response(422, json={"detail": [{"msg": "x"}]}), "Confira o valor"),
        (httpx.Response(500), "com problema agora"),
        (httpx.Response(201, json={}), "formato inesperado"),
    ],
)
def test_erros_da_api(resposta, erro):
    with pytest.raises(SpendwiseError, match=erro):
        lancar_com_api_falsa(lambda request: resposta)


def test_sem_internet():
    def responder(request):
        raise httpx.ConnectError("sem rede")

    with pytest.raises(SpendwiseError, match="Não consegui acessar o Spendwise"):
        lancar_com_api_falsa(responder)


def test_mensagens_de_erro_nao_mostram_a_chave():
    # Mesmo que o servidor devolvesse a chave no texto do erro.
    for status in (401, 403, 422, 500):
        with pytest.raises(SpendwiseError) as erro:
            lancar_com_api_falsa(
                lambda request, s=status: httpx.Response(s, json={"detail": f"chave {CHAVE} recusada"})
            )
        assert CHAVE not in str(erro.value)


def test_nao_segue_redirecionamento_para_outro_site():
    pedidos = []

    def responder(request):
        pedidos.append(request.url.host)
        return httpx.Response(307, headers={"Location": "https://outro-site.exemplo/gastos"})

    with pytest.raises(SpendwiseError, match="com problema agora"):
        lancar_com_api_falsa(responder)
    assert pedidos == ["spendwise.exemplo"]  # a chave não foi para o outro site


def test_pedido_com_tempo_maximo():
    tempos = []

    def responder(request):
        tempos.append(request.extensions["timeout"])
        return httpx.Response(201, json={"id": 1})

    lancar_com_api_falsa(responder)
    assert tempos[0]["read"] == 20


def test_valor_vai_com_duas_casas():
    corpos = []

    def responder(request):
        corpos.append(json.loads(request.content))
        return httpx.Response(201, json={"id": 1})

    async def rodar():
        async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as cliente:
            await lancar(Gasto(Decimal("35.900"), "x", "", HOJE), URL, CHAVE, cliente)

    asyncio.run(rodar())
    assert corpos[0]["valor"] == "35.90"


@pytest.mark.parametrize(
    ("gasto", "esperado"),
    [
        (Gasto(Decimal("35.9"), "mercado", "pão e leite", HOJE),
         "💸 Lançado no Spendwise: R$ 35,90 em mercado (pão e leite), hoje. (#42)"),
        (Gasto(Decimal("120"), "farmácia", "", date(2026, 10, 3)),
         "💸 Lançado no Spendwise: R$ 120,00 em farmácia, ontem. (#42)"),
        (Gasto(Decimal("50"), "uber", "", date(2026, 9, 20)),
         "💸 Lançado no Spendwise: R$ 50,00 em uber, 20/09/2026. (#42)"),
    ],
)
def test_confirmacao(gasto, esperado):
    assert confirmar(gasto, 42, HOJE) == esperado

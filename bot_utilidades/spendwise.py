"""Lança gastos no Spendwise (o controle de gastos do mesmo autor) pela API dele,
com uma chave de acesso: "/gasto 35 mercado pão e leite".

Não depende do Telegram: quem chama e responde é o bot.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import httpx

from bot_utilidades.alertas import AlertaError, ler_valor
from bot_utilidades.cotacoes import reais
from bot_utilidades.lembretes import FORMATO_DATA

USO = (
    "Use assim:\n"
    "/gasto 35 mercado (valor e categoria)\n"
    "/gasto 35,90 mercado pão e leite (com descrição)\n"
    "/gasto 120 farmácia ontem (ou com a data no fim: 20/09)"
)

# O Spendwise guarda até 12 dígitos contando os centavos: R$ 9.999.999.999,99.
VALOR_MAXIMO = Decimal("9999999999.99")

TAMANHO_DA_CATEGORIA = 40
TAMANHO_DA_DESCRICAO = 200

# A Vercel pode levar alguns segundos para acordar o servidor no primeiro pedido.
TEMPO_MAXIMO = 20


class SpendwiseError(Exception):
    """Pedido inválido ou erro da API; a mensagem vai para o usuário."""


@dataclass(frozen=True)
class Gasto:
    valor: Decimal
    categoria: str
    descricao: str
    data: date


def ler_data(texto: str, hoje: date) -> date | None:
    """"hoje", "ontem", "20/09" ou "20/09/2026" -> date; None se não for data.

    Sem ano, uma data que ainda não chegou é do ano passado (gasto é sempre passado).
    """
    palavra = texto.lower()
    if palavra == "hoje":
        return hoje
    if palavra == "ontem":
        return hoje - timedelta(days=1)
    if palavra == "anteontem":
        return hoje - timedelta(days=2)
    combinou = FORMATO_DATA.match(texto)
    if not combinou:
        return None
    dia, mes = int(combinou[1]), int(combinou[2])
    if combinou[3]:
        ano = int(combinou[3])
        try:
            return date(ano + 2000 if ano < 100 else ano, mes, dia)
        except ValueError:
            raise SpendwiseError(f'A data "{texto}" não existe.') from None
    # Sem ano: a última vez que a data passou. 29/02 volta até o último ano bissexto.
    for ano in range(hoje.year, hoje.year - 5, -1):
        try:
            data = date(ano, mes, dia)
        except ValueError:
            continue
        if data <= hoje:
            return data
    raise SpendwiseError(f'A data "{texto}" não existe.')


def interpretar(palavras: list[str], hoje: date) -> Gasto:
    """["35,90", "mercado", "pão", "e", "leite"] -> Gasto(35.90, "mercado", "pão e leite", hoje)."""
    if len(palavras) < 2:
        raise SpendwiseError(USO)
    try:
        valor = ler_valor(palavras[0])
    except AlertaError as erro:
        raise SpendwiseError(str(erro).split("\n\n")[0] + "\n\n" + USO) from None
    if valor != valor.quantize(Decimal("0.01")):
        raise SpendwiseError("O valor pode ter no máximo 2 casas depois da vírgula.")
    if valor > VALOR_MAXIMO:
        raise SpendwiseError("Esse valor é grande demais para o Spendwise.")

    resto = palavras[1:]
    if len(resto) == 1 and ler_data(resto[0], hoje) is not None:
        raise SpendwiseError("Faltou a categoria.\n" + USO)  # "/gasto 35 ontem"
    data = ler_data(resto[-1], hoje) if len(resto) > 1 else None
    if data is not None:
        resto = resto[:-1]
    if data is None:
        data = hoje
    if data > hoje:
        raise SpendwiseError("A data do gasto não pode ser no futuro.")

    categoria, descricao = resto[0].lower(), " ".join(resto[1:])
    if len(categoria) > TAMANHO_DA_CATEGORIA:
        raise SpendwiseError(f"A categoria pode ter até {TAMANHO_DA_CATEGORIA} caracteres.")
    if len(descricao) > TAMANHO_DA_DESCRICAO:
        raise SpendwiseError(f"A descrição pode ter até {TAMANHO_DA_DESCRICAO} caracteres.")
    return Gasto(valor, categoria, descricao, data)


async def lancar(gasto: Gasto, url: str, chave: str, cliente: httpx.AsyncClient) -> int:
    """Manda o gasto para o Spendwise e devolve o número (id) dele lá."""
    try:
        resposta = await cliente.post(
            f"{url}/gastos",
            json={
                "valor": format(gasto.valor.quantize(Decimal("0.01")), "f"),  # "35.90"
                "categoria": gasto.categoria,
                "descricao": gasto.descricao,
                "data": gasto.data.isoformat(),
            },
            # Só neste pedido: a chave nunca vai para as outras APIs do bot.
            headers={"Authorization": f"Bearer {chave}"},
            timeout=TEMPO_MAXIMO,
        )
    except httpx.HTTPError as erro:
        raise SpendwiseError("Não consegui acessar o Spendwise. Tente mais tarde.") from erro

    if resposta.status_code == 401:
        raise SpendwiseError(
            "O Spendwise não aceitou a chave (ela foi apagada?). Crie outra em "
            "Sua conta > Chaves de acesso e troque a SPENDWISE_CHAVE no .env do bot."
        )
    if resposta.status_code == 403:
        # O texto vem do servidor: a chave é apagada dele por garantia.
        raise SpendwiseError(f"O Spendwise recusou: {detalhe(resposta).replace(chave, '***')}")
    if resposta.status_code == 422:
        raise SpendwiseError("O Spendwise recusou o gasto. Confira o valor, a categoria e a data.")
    if resposta.status_code != 201:
        raise SpendwiseError("O Spendwise está com problema agora. Tente mais tarde.")
    try:
        return int(resposta.json()["id"])
    except (ValueError, KeyError, TypeError) as erro:
        raise SpendwiseError("O Spendwise respondeu num formato inesperado.") from erro


def detalhe(resposta: httpx.Response) -> str:
    try:
        texto = resposta.json()["detail"]
    except (ValueError, KeyError, TypeError):
        return "sem detalhes"
    return texto if isinstance(texto, str) else "sem detalhes"


def confirmar(gasto: Gasto, numero: int, hoje: date) -> str:
    quando = {hoje: "hoje", hoje - timedelta(days=1): "ontem"}.get(gasto.data, f"{gasto.data:%d/%m/%Y}")
    descricao = f" ({gasto.descricao})" if gasto.descricao else ""
    return f"💸 Lançado no Spendwise: {reais(gasto.valor, 2)} em {gasto.categoria}{descricao}, {quando}. (#{numero})"

"""Interpreta os pedidos da lista de compras e tarefas: "/add pão, leite",
"/add tarefas: estudar cálculo", "/feito 2 5" e "/limpar compras".

Não depende do Telegram: quem salva e responde é o bot.
"""

import re
from dataclasses import dataclass

LISTA_PADRAO = "compras"

# Limites para ninguém encher o banco. A /lista longa é dividida em várias mensagens
# (partir), porque o Telegram aceita até 4096 caracteres por mensagem.
LIMITE_POR_CHAT = 200
TAMANHO_DO_ITEM = 200
TAMANHO_DO_NOME = 30
TAMANHO_DA_MENSAGEM = 4096

# "/limpar tudo" apaga todas as listas, então nenhuma lista pode se chamar assim.
RESERVADO = "tudo"

# "tarefas: estudar" -> nome da lista antes dos dois-pontos (até 3 palavras). Os
# dois-pontos precisam vir seguidos de espaço: "10:30" e "http://" não são nome de lista.
FORMATO_NOME = re.compile(
    r"^\s*([^\s:,][^:,]{0,%d}?)\s*:(\s.*|)$" % (TAMANHO_DO_NOME - 1), re.DOTALL
)

USO_ADD = (
    "Use assim:\n"
    "/add pão, leite, ovos (na lista de compras)\n"
    "/add tarefas: estudar cálculo (numa lista com nome)"
)
USO_FEITO = "Use assim: /feito 2 (ou /feito 2 5 7)\nOs números aparecem em /lista"
USO_LIMPAR = (
    "Use assim:\n"
    "/limpar compras (esvazia uma lista)\n"
    "/limpar tudo (apaga todas as listas)"
)


class ListaError(Exception):
    """Pedido inválido; a mensagem vai para o usuário."""


@dataclass(frozen=True)
class Item:
    id: int
    chat_id: int
    lista: str
    texto: str


def nome_da_lista(texto: str) -> str:
    """" Mercado  do Mês " -> "mercado do mês"."""
    return " ".join(texto.lower().split())


def interpretar_add(texto: str) -> tuple[str, list[str]]:
    """"pão, leite" -> ("compras", ["pão", "leite"]); "tarefas: estudar" -> ("tarefas", ["estudar"])."""
    lista = LISTA_PADRAO
    combinou = FORMATO_NOME.match(texto)
    if combinou and len(combinou[1].split()) <= 3:
        lista, texto = nome_da_lista(combinou[1]), combinou[2]
        if lista == RESERVADO:
            raise ListaError('"tudo" não pode ser nome de lista (o /limpar tudo apaga todas).')
    itens = [" ".join(parte.split()) for parte in re.split(r"[,;\n]", texto)]
    itens = [item for item in itens if item]
    if not itens:
        raise ListaError(USO_ADD)
    if any(len(item) > TAMANHO_DO_ITEM for item in itens):
        raise ListaError(f"Cada item pode ter até {TAMANHO_DO_ITEM} caracteres.")
    return lista, itens


def ler_numeros(palavras: list[str]) -> list[int]:
    """["2", "#5", "7,8"] -> [2, 5, 7, 8], sem repetir."""
    partes = [parte.removeprefix("#") for palavra in palavras for parte in palavra.split(",") if parte]
    # Mais de 18 dígitos não cabe no INTEGER do SQLite (e nenhum item chega lá).
    if not partes or not all(parte.isdecimal() and len(parte) <= 18 for parte in partes):
        raise ListaError(USO_FEITO)
    return list(dict.fromkeys(int(parte) for parte in partes))


def quantos(total: int) -> str:
    """quantos(1) -> "1 item"; quantos(3) -> "3 itens"."""
    return f"{total} item" if total == 1 else f"{total} itens"


def partir(texto: str, limite: int = TAMANHO_DA_MENSAGEM) -> list[str]:
    """Divide o texto em mensagens de até `limite` caracteres, sem cortar linhas."""
    mensagens = [""]
    for linha in texto.split("\n"):
        while len(linha) > limite:  # uma linha sozinha maior que o limite (não acontece aqui)
            mensagens.append(linha[:limite])
            linha = linha[limite:]
        junto = f"{mensagens[-1]}\n{linha}" if mensagens[-1] else linha
        if len(junto) <= limite:
            mensagens[-1] = junto
        else:
            mensagens.append(linha)
    return [mensagem for mensagem in mensagens if mensagem.strip()]


def confirmar_add(lista: str, itens: list[Item]) -> str:
    """"📝 Na lista de compras: #1 pão, #2 leite" ou, com muitos itens, só a contagem."""
    nomes = ", ".join(f"#{item.id} {item.texto}" for item in itens)
    if len(nomes) > 1000:
        return f"📝 {quantos(len(itens))} na lista de {lista} (#{itens[0].id} a #{itens[-1].id})."
    return f"📝 Na lista de {lista}: {nomes}"


def formatar(itens: list[Item]) -> str:
    """Os itens agrupados por lista, cada lista na ordem do seu primeiro item."""
    listas: dict[str, list[Item]] = {}
    for item in itens:
        listas.setdefault(item.lista, []).append(item)
    blocos = [
        f"{nome.capitalize()}:\n" + "\n".join(f"#{item.id} {item.texto}" for item in grupo)
        for nome, grupo in listas.items()
    ]
    return "\n\n".join(blocos) + "\n\nQuando terminar: /feito número"

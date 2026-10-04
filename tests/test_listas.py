import pytest

from bot_utilidades.listas import (
    Item,
    ListaError,
    confirmar_add,
    formatar,
    interpretar_add,
    ler_numeros,
    nome_da_lista,
    partir,
    quantos,
)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("pão", ("compras", ["pão"])),
        ("pão, leite,ovos", ("compras", ["pão", "leite", "ovos"])),
        ("pão; leite\novos", ("compras", ["pão", "leite", "ovos"])),
        ("  arroz   integral ,, ", ("compras", ["arroz integral"])),
        ("tarefas: estudar cálculo, ler", ("tarefas", ["estudar cálculo", "ler"])),
        ("Mercado  do Mês: arroz", ("mercado do mês", ["arroz"])),
        ("obs: a: b", ("obs", ["a: b"])),
    ],
)
def test_interpreta_o_add(texto, esperado):
    assert interpretar_add(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    ["ligar 10:30 pro banco", "http://exemplo.com", "um dois tres quatro: x", "tarefas:estudar"],
)
def test_dois_pontos_que_nao_sao_nome_de_lista(texto):
    lista, itens = interpretar_add(texto)
    assert lista == "compras"
    assert ", ".join(itens) == texto


@pytest.mark.parametrize("texto", ["", "   ", ",,", "tarefas:", "tarefas: , "])
def test_add_vazio_mostra_como_usar(texto):
    with pytest.raises(ListaError, match="Use assim"):
        interpretar_add(texto)


def test_item_longo_demais():
    assert interpretar_add("a" * 200)[1] == ["a" * 200]
    with pytest.raises(ListaError, match="até 200 caracteres"):
        interpretar_add("a" * 201)


def test_nome_da_lista():
    assert nome_da_lista("  Mercado   do Mês ") == "mercado do mês"
    assert nome_da_lista("") == ""


@pytest.mark.parametrize(
    ("palavras", "esperado"),
    [(["2"], [2]), (["#2", "5"], [2, 5]), (["2,5,", "7"], [2, 5, 7]), (["3", "3"], [3])],
)
def test_le_numeros(palavras, esperado):
    assert ler_numeros(palavras) == esperado


@pytest.mark.parametrize("palavras", [[], ["dois"], ["2", "x"], ["-1"], [","], ["9" * 19]])
def test_numeros_invalidos(palavras):
    with pytest.raises(ListaError, match="Use assim: /feito 2"):
        ler_numeros(palavras)


def test_formata_por_lista():
    itens = [
        Item(1, 42, "compras", "pão"),
        Item(3, 42, "compras", "leite"),
        Item(2, 42, "tarefas", "estudar"),
    ]
    assert formatar(itens) == (
        "Compras:\n#1 pão\n#3 leite\n\nTarefas:\n#2 estudar\n\nQuando terminar: /feito número"
    )


def test_quantos():
    assert (quantos(0), quantos(1), quantos(2)) == ("0 itens", "1 item", "2 itens")


@pytest.mark.parametrize("texto", ["tudo: x", "Tudo : x"])
def test_lista_nao_pode_se_chamar_tudo(texto):
    with pytest.raises(ListaError, match='"tudo" não pode ser nome de lista'):
        interpretar_add(texto)


def test_itens_de_listas_misturadas_ficam_agrupados():
    itens = [Item(1, 42, "compras", "pão"), Item(2, 42, "tarefas", "ler"), Item(3, 42, "compras", "ovos")]
    assert formatar(itens).startswith("Compras:\n#1 pão\n#3 ovos\n\nTarefas:\n#2 ler")


def test_partir_respeita_o_limite_sem_cortar_linhas():
    linhas = [f"#{i} " + "a" * 200 for i in range(200)]
    mensagens = partir("\n".join(linhas))
    assert len(mensagens) > 1
    assert all(len(m) <= 4096 for m in mensagens)
    assert "\n".join(mensagens).split("\n") == linhas


def test_partir_texto_curto_e_linha_gigante():
    assert partir("a\nb") == ["a\nb"]
    assert partir("x" * 10, limite=4) == ["xxxx", "xxxx", "xx"]


def test_lista_cheia_cabe_nas_mensagens():
    itens = [Item(i, 42, "compras", "a" * 200) for i in range(1, 201)]
    mensagens = partir(formatar(itens))
    assert all(len(m) <= 4096 for m in mensagens)
    assert sum(m.count("#") for m in mensagens) == 200


def test_confirmacao_do_add():
    poucos = [Item(1, 42, "compras", "pão"), Item(2, 42, "compras", "leite")]
    assert confirmar_add("compras", poucos) == "📝 Na lista de compras: #1 pão, #2 leite"
    muitos = [Item(i, 42, "compras", "a" * 200) for i in range(5, 15)]
    assert confirmar_add("compras", muitos) == "📝 10 itens na lista de compras (#5 a #14)."

from datetime import datetime, timedelta, timezone

from bot_utilidades.armazenamento import Banco
from bot_utilidades.lembretes import FUSO

QUANDO = datetime(2026, 9, 27, 14, 30, tzinfo=FUSO)


def test_adiciona_e_busca(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    lembrete = banco.adicionar(42, "tomar água", QUANDO)

    assert lembrete.id == 1
    assert lembrete.chat_id == 42
    assert lembrete.texto == "tomar água"
    assert lembrete.quando == QUANDO
    assert banco.buscar(lembrete.id) == lembrete


def test_guarda_em_utc(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    lembrete = banco.adicionar(42, "reunião", QUANDO)
    # 14:30 em Brasília (UTC-3) são 17:30 em UTC; o instante é o mesmo.
    assert lembrete.quando.tzinfo == timezone.utc
    assert lembrete.quando.hour == 17


def test_sobrevive_a_reabrir_o_banco(tmp_path):
    Banco(tmp_path / "lembretes.db").adicionar(42, "tomar água", QUANDO)
    [lembrete] = Banco(tmp_path / "lembretes.db").todos()
    assert lembrete.texto == "tomar água"


def test_cria_a_pasta_do_banco(tmp_path):
    Banco(tmp_path / "dados" / "lembretes.db")
    assert (tmp_path / "dados" / "lembretes.db").exists()


def test_todos_em_ordem_de_horario(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    banco.adicionar(1, "depois", QUANDO + timedelta(days=1))
    banco.adicionar(2, "antes", QUANDO)
    banco.adicionar(1, "no meio", QUANDO + timedelta(hours=2))
    assert [l.texto for l in banco.todos()] == ["antes", "no meio", "depois"]


def test_conta_por_chat(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    banco.adicionar(1, "a", QUANDO)
    banco.adicionar(1, "b", QUANDO)
    banco.adicionar(2, "c", QUANDO)
    assert banco.contar(1) == 2
    assert banco.contar(2) == 1
    assert banco.contar(3) == 0


def test_remove(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    lembrete = banco.adicionar(42, "tomar água", QUANDO)
    assert banco.remover(lembrete.id) is True
    assert banco.buscar(lembrete.id) is None
    assert banco.remover(lembrete.id) is False


def test_numeros_nao_sao_reaproveitados(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    primeiro = banco.adicionar(42, "a", QUANDO)
    banco.remover(primeiro.id)
    # Sem AUTOINCREMENT o SQLite devolveria o 1 de novo, e um /cancelar 1
    # atrasado apagaria o lembrete errado.
    assert banco.adicionar(42, "b", QUANDO).id == 2

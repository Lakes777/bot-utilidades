import sqlite3
from contextlib import closing
from decimal import Decimal
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


def test_lembretes_do_chat(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    banco.adicionar(1, "depois", QUANDO + timedelta(hours=1))
    banco.adicionar(2, "de outra pessoa", QUANDO)
    banco.adicionar(1, "antes", QUANDO)
    assert [l.texto for l in banco.do_chat(1)] == ["antes", "depois"]
    assert banco.do_chat(3) == []


def test_cancela_so_do_proprio_chat(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    lembrete = banco.adicionar(1, "meu", QUANDO)

    assert banco.cancelar(lembrete.id, chat_id=2) is None
    assert banco.buscar(lembrete.id) == lembrete

    assert banco.cancelar(lembrete.id, chat_id=1) == lembrete
    assert banco.buscar(lembrete.id) is None
    assert banco.cancelar(lembrete.id, chat_id=1) is None


def test_lembrete_diario(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    assert banco.adicionar(1, "avulso", QUANDO).diario is False
    diario = banco.adicionar(1, "remédio", QUANDO, diario=True)
    assert diario.diario is True
    assert Banco(tmp_path / "lembretes.db").buscar(diario.id).diario is True


def test_lembrete_semanal(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    assert banco.adicionar(1, "avulso", QUANDO).semanal is False
    semanal = banco.adicionar(1, "futebol", QUANDO, semanal=True)
    assert semanal.semanal is True and semanal.diario is False
    assert Banco(tmp_path / "lembretes.db").buscar(semanal.id).semanal is True


def test_guarda_os_dias_da_semana(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    salvo = banco.adicionar(1, "academia", QUANDO, semanal=True, dias=(0, 2, 4))
    assert Banco(tmp_path / "lembretes.db").buscar(salvo.id).dias == (0, 2, 4)
    assert banco.adicionar(1, "avulso", QUANDO).dias == ()


def test_semanal_sem_dias_usa_o_dia_da_data(tmp_path):
    # Semanais criados antes da coluna "dias": QUANDO é um domingo em Brasília.
    banco = Banco(tmp_path / "lembretes.db")
    assert banco.adicionar(1, "feira", QUANDO, semanal=True).dias == (6,)


def test_guarda_o_dia_do_mes(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    mensal = banco.adicionar(1, "aluguel", QUANDO, dia_do_mes=10)
    assert Banco(tmp_path / "lembretes.db").buscar(mensal.id).dia_do_mes == 10
    assert mensal.repete
    avulso = banco.adicionar(1, "avulso", QUANDO)
    assert avulso.dia_do_mes is None and not avulso.repete


def test_banco_do_servidor_com_semanal_e_sem_dias(tmp_path):
    # Formato do banco da Oracle depois de 04/10: tem "semanal", ainda não tem "dias".
    caminho = tmp_path / "lembretes.db"
    with closing(sqlite3.connect(caminho)) as conexao, conexao:
        conexao.execute(
            "CREATE TABLE lembretes (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,"
            " texto TEXT NOT NULL, quando TEXT NOT NULL,"
            " diario INTEGER NOT NULL DEFAULT 0 CHECK (diario IN (0, 1)),"
            " semanal INTEGER NOT NULL DEFAULT 0 CHECK (semanal IN (0, 1)))"
        )
        # Quinta 01/10/2026 às 19:00 em Brasília = 22:00 em UTC.
        conexao.execute(
            "INSERT INTO lembretes (chat_id, texto, quando, diario, semanal)"
            " VALUES (42, 'futebol', '2026-10-01 22:00:00', 0, 1)"
        )

    [antigo] = Banco(caminho).todos()
    assert antigo.semanal and antigo.dias == (3,) and antigo.dia_do_mes is None


def test_banco_do_servidor_com_dias_e_sem_dia_do_mes(tmp_path):
    # Formato do banco da Oracle depois do commit dos vários dias.
    caminho = tmp_path / "lembretes.db"
    with closing(sqlite3.connect(caminho)) as conexao, conexao:
        conexao.execute(
            "CREATE TABLE lembretes (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,"
            " texto TEXT NOT NULL, quando TEXT NOT NULL,"
            " diario INTEGER NOT NULL DEFAULT 0 CHECK (diario IN (0, 1)),"
            " semanal INTEGER NOT NULL DEFAULT 0 CHECK (semanal IN (0, 1)), dias TEXT)"
        )
        conexao.execute(
            "INSERT INTO lembretes (chat_id, texto, quando, semanal, dias)"
            " VALUES (42, 'academia', '2026-09-28 10:00:00', 1, '0,2')"
        )

    banco = Banco(caminho)
    [antigo] = banco.todos()
    assert antigo.dias == (0, 2) and antigo.dia_do_mes is None
    assert banco.buscar(banco.adicionar(42, "aluguel", QUANDO, dia_do_mes=10).id).dia_do_mes == 10


def test_acrescenta_a_coluna_semanal_num_banco_antigo(tmp_path):
    # Banco criado antes dos lembretes semanais, como o que já está no servidor.
    caminho = tmp_path / "lembretes.db"
    with closing(sqlite3.connect(caminho)) as conexao, conexao:
        conexao.execute(
            "CREATE TABLE lembretes (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,"
            " texto TEXT NOT NULL, quando TEXT NOT NULL,"
            " diario INTEGER NOT NULL DEFAULT 0 CHECK (diario IN (0, 1)))"
        )
        conexao.execute(
            "INSERT INTO lembretes (chat_id, texto, quando, diario)"
            " VALUES (42, 'remédio', '2026-09-27 11:00:00', 1)"
        )

    banco = Banco(caminho)
    [antigo] = banco.todos()
    assert antigo.texto == "remédio" and antigo.diario and not antigo.semanal
    assert antigo.dias == ()
    novo = banco.adicionar(42, "futebol", QUANDO, semanal=True)
    assert banco.buscar(novo.id).semanal

    Banco(caminho)  # abrir de novo não tenta acrescentar a coluna outra vez
    assert len(Banco(caminho).todos()) == 2


def test_envios_registrados_e_tirados(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    enviado = banco.registrar_envio(42, "tomar água", QUANDO)

    assert banco.tirar_envio(enviado.id, 7) is None  # outro chat
    assert banco.tirar_envio(enviado.id, 42) == enviado
    assert banco.tirar_envio(enviado.id, 42) is None  # só uma vez


def test_envios_antigos_sao_apagados(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    antigo = banco.registrar_envio(42, "velho", QUANDO)
    recente = banco.registrar_envio(42, "recente", QUANDO + timedelta(days=6))

    banco.registrar_envio(42, "novo", QUANDO + timedelta(days=7, seconds=1))

    assert banco.tirar_envio(antigo.id, 42) is None
    assert banco.tirar_envio(recente.id, 42) == recente


def test_mudar_so_no_proprio_chat(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    lembrete = banco.adicionar(42, "remédio", QUANDO, diario=True)
    novo = QUANDO + timedelta(hours=2)

    assert banco.mudar(lembrete.id, 7, novo) is None
    assert banco.buscar(lembrete.id) == lembrete

    mudado = banco.mudar(lembrete.id, 42, novo, semanal=True, dias=(0, 2))
    assert mudado.quando == novo and mudado.semanal and not mudado.diario
    assert mudado.dias == (0, 2) and mudado.texto == "remédio"


def test_adiar_e_remover_so_se_a_data_nao_mudou(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    lembrete = banco.adicionar(42, "remédio", QUANDO, diario=True)
    outra = QUANDO + timedelta(hours=1)

    assert banco.adiar(lembrete.id, outra, se_quando=outra) is None
    assert banco.remover(lembrete.id, se_quando=outra) is False
    assert banco.buscar(lembrete.id) == lembrete

    assert banco.adiar(lembrete.id, outra, se_quando=QUANDO).quando == outra
    assert banco.remover(lembrete.id, se_quando=outra) is True


def test_adiar(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    diario = banco.adicionar(1, "remédio", QUANDO, diario=True)
    amanha = QUANDO + timedelta(days=1)

    adiado = banco.adiar(diario.id, amanha)

    assert adiado.quando == amanha
    assert adiado.diario and adiado.texto == "remédio"
    assert banco.buscar(diario.id) == adiado


def test_alertas_salvos_listados_e_apagados(tmp_path):
    banco = Banco(tmp_path / "lembretes.db")
    a = banco.adicionar_alerta(1, "BTC-BRL", "acima", Decimal("400000.50"))
    banco.adicionar_alerta(2, "USD-BRL", "abaixo", Decimal("5.20"))

    assert a.valor == Decimal("400000.50")  # Decimal exato, sem virar float
    assert [x.chat_id for x in banco.todos_alertas()] == [1, 2]
    assert banco.alertas_do_chat(1) == [a]
    assert banco.cancelar_alerta(a.id, chat_id=2) is None  # de outro chat, não apaga
    assert banco.cancelar_alerta(a.id, chat_id=1) == a
    assert not banco.remover_alerta(a.id)
    # Reabrir o arquivo mantém o que sobrou (sobrevive a reinicializações).
    assert len(Banco(tmp_path / "lembretes.db").todos_alertas()) == 1

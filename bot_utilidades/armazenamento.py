"""Guarda os lembretes num arquivo SQLite, para sobreviverem a reinicializações.

Usa o sqlite3 que já vem com o Python, com SQL escrito à mão, sem ORM.
Cada operação abre e fecha a própria conexão.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

CAMINHO_PADRAO = Path("dados/lembretes.db")

# Datas sempre em UTC e sempre no mesmo formato: assim a ordem alfabética
# da coluna é a ordem cronológica, e o ORDER BY funciona direto no texto.
FORMATO_DATA = "%Y-%m-%d %H:%M:%S"

CRIAR_TABELA = """
CREATE TABLE IF NOT EXISTS lembretes (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,  -- AUTOINCREMENT: números não são reaproveitados
    chat_id INTEGER NOT NULL,
    texto   TEXT    NOT NULL,
    quando  TEXT    NOT NULL  -- data e hora em UTC, no FORMATO_DATA
)
"""


@dataclass(frozen=True)
class Lembrete:
    id: int
    chat_id: int
    texto: str
    quando: datetime  # sempre com fuso (UTC)


def para_texto(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).strftime(FORMATO_DATA)


def de_texto(texto: str) -> datetime:
    return datetime.strptime(texto, FORMATO_DATA).replace(tzinfo=timezone.utc)


class Banco:
    def __init__(self, caminho: Path | str = CAMINHO_PADRAO) -> None:
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._conectar() as conexao:
            conexao.execute(CRIAR_TABELA)

    @contextmanager
    def _conectar(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.caminho)) as conexao:
            conexao.row_factory = sqlite3.Row  # linhas acessíveis por nome: linha["texto"]
            with conexao:  # confirma (commit) no final, ou desfaz tudo se der erro
                yield conexao

    @staticmethod
    def _lembrete(linha: sqlite3.Row) -> Lembrete:
        return Lembrete(linha["id"], linha["chat_id"], linha["texto"], de_texto(linha["quando"]))

    def adicionar(self, chat_id: int, texto: str, quando: datetime) -> Lembrete:
        with self._conectar() as conexao:
            cursor = conexao.execute(
                "INSERT INTO lembretes (chat_id, texto, quando) VALUES (?, ?, ?)",
                (chat_id, texto, para_texto(quando)),
            )
        return self.buscar(cursor.lastrowid)

    def buscar(self, id: int) -> Lembrete | None:
        with self._conectar() as conexao:
            linha = conexao.execute("SELECT * FROM lembretes WHERE id = ?", (id,)).fetchone()
        return self._lembrete(linha) if linha else None

    def todos(self) -> list[Lembrete]:
        """Todos os lembretes pendentes, de todos os chats (para reagendar ao iniciar)."""
        with self._conectar() as conexao:
            linhas = conexao.execute("SELECT * FROM lembretes ORDER BY quando, id").fetchall()
        return [self._lembrete(linha) for linha in linhas]

    def do_chat(self, chat_id: int) -> list[Lembrete]:
        """Os lembretes de um chat, do mais próximo ao mais distante."""
        with self._conectar() as conexao:
            linhas = conexao.execute(
                "SELECT * FROM lembretes WHERE chat_id = ? ORDER BY quando, id", (chat_id,)
            ).fetchall()
        return [self._lembrete(linha) for linha in linhas]

    def contar(self, chat_id: int) -> int:
        with self._conectar() as conexao:
            [total] = conexao.execute(
                "SELECT COUNT(*) FROM lembretes WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        return total

    def remover(self, id: int) -> bool:
        """Apaga o lembrete; devolve False se ele não existia."""
        with self._conectar() as conexao:
            cursor = conexao.execute("DELETE FROM lembretes WHERE id = ?", (id,))
        return cursor.rowcount > 0

    def cancelar(self, id: int, chat_id: int) -> Lembrete | None:
        """Apaga o lembrete só se ele for deste chat; devolve o que foi apagado."""
        with self._conectar() as conexao:
            linha = conexao.execute(
                "SELECT * FROM lembretes WHERE id = ? AND chat_id = ?", (id, chat_id)
            ).fetchone()
            if linha is None:
                return None
            conexao.execute("DELETE FROM lembretes WHERE id = ?", (id,))
        return self._lembrete(linha)

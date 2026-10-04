"""Guarda os lembretes e os alertas num arquivo SQLite, para sobreviverem a reinicializações.

Usa o sqlite3 que já vem com o Python, com SQL escrito à mão, sem ORM.
Cada operação abre e fecha a própria conexão.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from bot_utilidades.lembretes import FUSO

CAMINHO_PADRAO = Path("dados/lembretes.db")

# Datas sempre em UTC e sempre no mesmo formato: assim a ordem alfabética
# da coluna é a ordem cronológica, e o ORDER BY funciona direto no texto.
FORMATO_DATA = "%Y-%m-%d %H:%M:%S"

CRIAR_TABELA = """
CREATE TABLE IF NOT EXISTS lembretes (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,  -- AUTOINCREMENT: números não são reaproveitados
    chat_id INTEGER NOT NULL,
    texto   TEXT    NOT NULL,
    quando  TEXT    NOT NULL,  -- data e hora em UTC, no FORMATO_DATA (a próxima, se for diário)
    diario  INTEGER NOT NULL DEFAULT 0 CHECK (diario IN (0, 1)),  -- 1 = repete todo dia
    semanal INTEGER NOT NULL DEFAULT 0 CHECK (semanal IN (0, 1)),  -- 1 = repete toda semana
    dias    TEXT,  -- dias da semana dos semanais, ex.: "0,2" (segunda = 0)
    dia_do_mes INTEGER CHECK (dia_do_mes BETWEEN 1 AND 31)  -- só nos mensais
)
"""

# Colunas que bancos mais antigos não têm: são acrescentadas ao abrir, e os
# lembretes que já existiam ficam com o valor padrão.
COLUNAS_NOVAS = {
    "semanal": "ALTER TABLE lembretes ADD COLUMN semanal INTEGER NOT NULL DEFAULT 0"
    " CHECK (semanal IN (0, 1))",
    "dias": "ALTER TABLE lembretes ADD COLUMN dias TEXT",
    "dia_do_mes": "ALTER TABLE lembretes ADD COLUMN dia_do_mes INTEGER"
    " CHECK (dia_do_mes BETWEEN 1 AND 31)",
}


CRIAR_TABELA_ALERTAS = """
CREATE TABLE IF NOT EXISTS alertas (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    par     TEXT    NOT NULL,  -- como a API chama a moeda, ex.: "BTC-BRL"
    direcao TEXT    NOT NULL CHECK (direcao IN ('acima', 'abaixo')),
    valor   TEXT    NOT NULL   -- texto, não REAL: REAL é float e perderia centavos
)
"""


CRIAR_TABELA_ENVIADOS = """
CREATE TABLE IF NOT EXISTS enviados (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    texto      TEXT    NOT NULL,
    enviado_em TEXT    NOT NULL  -- UTC, no FORMATO_DATA
)
"""

# Os botões de um lembrete enviado funcionam por este tempo; depois o registro é apagado.
VALIDADE_DOS_BOTOES = timedelta(days=7)


@dataclass(frozen=True)
class Enviado:
    """Um lembrete já entregue, guardado só para os botões "Adiar" saberem o texto."""

    id: int
    chat_id: int
    texto: str


@dataclass(frozen=True)
class Alerta:
    id: int
    chat_id: int
    par: str
    direcao: str
    valor: Decimal


@dataclass(frozen=True)
class Lembrete:
    id: int
    chat_id: int
    texto: str
    quando: datetime  # sempre com fuso (UTC)
    diario: bool = False
    semanal: bool = False
    dias: tuple[int, ...] = ()  # dias da semana dos semanais (segunda = 0)
    dia_do_mes: int | None = None  # só nos mensais

    @property
    def repete(self) -> bool:
        return self.diario or self.semanal or self.dia_do_mes is not None


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
            conexao.execute(CRIAR_TABELA_ALERTAS)
            conexao.execute(CRIAR_TABELA_ENVIADOS)
            colunas = {linha["name"] for linha in conexao.execute("PRAGMA table_info(lembretes)")}
            for coluna, acrescentar in COLUNAS_NOVAS.items():
                if coluna not in colunas:
                    conexao.execute(acrescentar)

    @contextmanager
    def _conectar(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.caminho)) as conexao:
            conexao.row_factory = sqlite3.Row  # linhas acessíveis por nome: linha["texto"]
            with conexao:  # confirma (commit) no final, ou desfaz tudo se der erro
                yield conexao

    @staticmethod
    def _lembrete(linha: sqlite3.Row) -> Lembrete:
        quando = de_texto(linha["quando"])
        dias = tuple(int(dia) for dia in linha["dias"].split(",")) if linha["dias"] else ()
        if linha["semanal"] and not dias:
            # Semanal de antes da coluna "dias": o dia vem da data do próximo envio.
            dias = (quando.astimezone(FUSO).weekday(),)
        return Lembrete(
            linha["id"],
            linha["chat_id"],
            linha["texto"],
            quando,
            bool(linha["diario"]),
            bool(linha["semanal"]),
            dias,
            linha["dia_do_mes"],
        )

    def adicionar(
        self,
        chat_id: int,
        texto: str,
        quando: datetime,
        diario: bool = False,
        semanal: bool = False,
        dias: tuple[int, ...] = (),
        dia_do_mes: int | None = None,
    ) -> Lembrete:
        with self._conectar() as conexao:
            cursor = conexao.execute(
                "INSERT INTO lembretes (chat_id, texto, quando, diario, semanal, dias, dia_do_mes)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    chat_id,
                    texto,
                    para_texto(quando),
                    int(diario),
                    int(semanal),
                    ",".join(str(dia) for dia in dias) or None,
                    dia_do_mes,
                ),
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

    def remover(self, id: int, se_quando: datetime | None = None) -> bool:
        """Apaga o lembrete; devolve False se ele não existia.

        Com se_quando, só apaga se a data ainda for essa (ninguém mudou no meio do envio).
        """
        sql, parametros = "DELETE FROM lembretes WHERE id = ?", [id]
        if se_quando is not None:
            sql += " AND quando = ?"
            parametros.append(para_texto(se_quando))
        with self._conectar() as conexao:
            cursor = conexao.execute(sql, parametros)
        return cursor.rowcount > 0

    def adiar(
        self, id: int, quando: datetime, se_quando: datetime | None = None
    ) -> Lembrete | None:
        """Muda a data do lembrete (usado pelos repetidos depois de cada envio).

        Com se_quando, só muda se a data ainda for essa; senão devolve None.
        """
        sql, parametros = "UPDATE lembretes SET quando = ? WHERE id = ?", [para_texto(quando), id]
        if se_quando is not None:
            sql += " AND quando = ?"
            parametros.append(para_texto(se_quando))
        with self._conectar() as conexao:
            cursor = conexao.execute(sql, parametros)
        return self.buscar(id) if cursor.rowcount else None

    def mudar(
        self,
        id: int,
        chat_id: int,
        quando: datetime,
        diario: bool = False,
        semanal: bool = False,
        dias: tuple[int, ...] = (),
        dia_do_mes: int | None = None,
    ) -> Lembrete | None:
        """Troca o quando e a repetição, só se o lembrete for deste chat."""
        with self._conectar() as conexao:
            cursor = conexao.execute(
                "UPDATE lembretes SET quando = ?, diario = ?, semanal = ?, dias = ?, dia_do_mes = ?"
                " WHERE id = ? AND chat_id = ?",
                (
                    para_texto(quando),
                    int(diario),
                    int(semanal),
                    ",".join(str(dia) for dia in dias) or None,
                    dia_do_mes,
                    id,
                    chat_id,
                ),
            )
        return self.buscar(id) if cursor.rowcount else None

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

    # ---------- Lembretes enviados (para os botões) ----------

    def registrar_envio(self, chat_id: int, texto: str, agora: datetime) -> Enviado:
        """Guarda o lembrete que vai ser enviado e apaga os registros vencidos."""
        with self._conectar() as conexao:
            conexao.execute(
                "DELETE FROM enviados WHERE enviado_em < ?",
                (para_texto(agora - VALIDADE_DOS_BOTOES),),
            )
            cursor = conexao.execute(
                "INSERT INTO enviados (chat_id, texto, enviado_em) VALUES (?, ?, ?)",
                (chat_id, texto, para_texto(agora)),
            )
        return Enviado(cursor.lastrowid, chat_id, texto)

    def buscar_envio(self, id: int, chat_id: int) -> Enviado | None:
        with self._conectar() as conexao:
            linha = conexao.execute(
                "SELECT * FROM enviados WHERE id = ? AND chat_id = ?", (id, chat_id)
            ).fetchone()
        return Enviado(linha["id"], linha["chat_id"], linha["texto"]) if linha else None

    def tirar_envio(self, id: int, chat_id: int) -> Enviado | None:
        """Apaga e devolve o registro, só se for deste chat (cada botão vale uma vez).

        Um DELETE só, conferido pelo rowcount: se dois cliques chegarem juntos,
        apenas um consegue apagar.
        """
        enviado = self.buscar_envio(id, chat_id)
        if enviado is None:
            return None
        with self._conectar() as conexao:
            cursor = conexao.execute(
                "DELETE FROM enviados WHERE id = ? AND chat_id = ?", (id, chat_id)
            )
        return enviado if cursor.rowcount > 0 else None

    def esquecer_envio(self, id: int) -> None:
        """Apaga o registro sem conferir o chat (usado quando o envio falha)."""
        with self._conectar() as conexao:
            conexao.execute("DELETE FROM enviados WHERE id = ?", (id,))

    # ---------- Alertas de preço ----------

    @staticmethod
    def _alerta(linha: sqlite3.Row) -> Alerta:
        return Alerta(
            linha["id"], linha["chat_id"], linha["par"], linha["direcao"], Decimal(linha["valor"])
        )

    def adicionar_alerta(self, chat_id: int, par: str, direcao: str, valor: Decimal) -> Alerta:
        with self._conectar() as conexao:
            cursor = conexao.execute(
                "INSERT INTO alertas (chat_id, par, direcao, valor) VALUES (?, ?, ?, ?)",
                (chat_id, par, direcao, str(valor)),
            )
            linha = conexao.execute(
                "SELECT * FROM alertas WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._alerta(linha)

    def todos_alertas(self) -> list[Alerta]:
        """Todos os alertas pendentes, de todos os chats (para conferir as cotações)."""
        with self._conectar() as conexao:
            linhas = conexao.execute("SELECT * FROM alertas ORDER BY id").fetchall()
        return [self._alerta(linha) for linha in linhas]

    def alertas_do_chat(self, chat_id: int) -> list[Alerta]:
        with self._conectar() as conexao:
            linhas = conexao.execute(
                "SELECT * FROM alertas WHERE chat_id = ? ORDER BY id", (chat_id,)
            ).fetchall()
        return [self._alerta(linha) for linha in linhas]

    def restaurar_alerta(self, alerta: Alerta) -> None:
        """Põe de volta um alerta apagado, com o mesmo número (usado se o envio falhar)."""
        with self._conectar() as conexao:
            conexao.execute(
                "INSERT OR IGNORE INTO alertas (id, chat_id, par, direcao, valor) VALUES (?, ?, ?, ?, ?)",
                (alerta.id, alerta.chat_id, alerta.par, alerta.direcao, str(alerta.valor)),
            )

    def remover_alerta(self, id: int) -> bool:
        with self._conectar() as conexao:
            cursor = conexao.execute("DELETE FROM alertas WHERE id = ?", (id,))
        return cursor.rowcount > 0

    def cancelar_alerta(self, id: int, chat_id: int) -> Alerta | None:
        """Apaga o alerta só se ele for deste chat; devolve o que foi apagado."""
        with self._conectar() as conexao:
            linha = conexao.execute(
                "SELECT * FROM alertas WHERE id = ? AND chat_id = ?", (id, chat_id)
            ).fetchone()
            if linha is None:
                return None
            conexao.execute("DELETE FROM alertas WHERE id = ?", (id,))
        return self._alerta(linha)

import pytest

from bot_utilidades.config import (
    ConfigError,
    carregar_chave_cotacoes,
    carregar_permitidos,
    carregar_spendwise,
    carregar_token,
)

TOKEN_FALSO = "123456789:" + "A" * 35


@pytest.fixture(autouse=True)
def sem_token_no_ambiente(monkeypatch):
    """Garante que o token real do seu .env nunca entre nos testes."""
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("AWESOMEAPI_TOKEN", raising=False)
    monkeypatch.delenv("SPENDWISE_CHAVE", raising=False)
    monkeypatch.delenv("SPENDWISE_URL", raising=False)


def test_le_token_do_arquivo_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"TELEGRAM_TOKEN={TOKEN_FALSO}\n")
    assert carregar_token(env) == TOKEN_FALSO


def test_variavel_de_ambiente_tem_prioridade(tmp_path, monkeypatch):
    outro = "987654321:" + "B" * 35
    monkeypatch.setenv("TELEGRAM_TOKEN", outro)
    env = tmp_path / ".env"
    env.write_text(f"TELEGRAM_TOKEN={TOKEN_FALSO}\n")
    assert carregar_token(env) == outro


def test_erro_claro_quando_nao_ha_token(tmp_path):
    with pytest.raises(ConfigError, match="não encontrado"):
        carregar_token(tmp_path / "nao-existe.env")


def test_recusa_o_texto_do_exemplo(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_TOKEN=cole-seu-token-aqui\n")
    with pytest.raises(ConfigError, match="formato inválido"):
        carregar_token(env)


@pytest.fixture(autouse=True)
def sem_permitidos_no_ambiente(monkeypatch):
    monkeypatch.delenv("USUARIOS_PERMITIDOS", raising=False)


def test_sem_lista_de_permitidos_fica_aberto(tmp_path):
    env = tmp_path / ".env"
    env.write_text("USUARIOS_PERMITIDOS=\n")
    assert carregar_permitidos(env) is None
    assert carregar_permitidos(tmp_path / "nao-existe.env") is None


@pytest.mark.parametrize("valor", ["111,222", "111, 222", " 111 222 ", "111,222,111"])
def test_le_lista_de_permitidos(tmp_path, valor):
    env = tmp_path / ".env"
    env.write_text(f"USUARIOS_PERMITIDOS={valor}\n")
    assert carregar_permitidos(env) == {111, 222}


@pytest.mark.parametrize("valor", ["111,abc", "@lakes777", "111;222", "-5"])
def test_recusa_ids_invalidos(tmp_path, valor):
    env = tmp_path / ".env"
    env.write_text(f"USUARIOS_PERMITIDOS={valor}\n")
    with pytest.raises(ConfigError, match="valor inválido"):
        carregar_permitidos(env)


def test_sem_chave_das_cotacoes(tmp_path):
    env = tmp_path / ".env"
    env.write_text("AWESOMEAPI_TOKEN=\n")
    assert carregar_chave_cotacoes(env) is None


def test_le_a_chave_das_cotacoes(tmp_path):
    env = tmp_path / ".env"
    env.write_text("AWESOMEAPI_TOKEN= abc123 \n")
    assert carregar_chave_cotacoes(env) == "abc123"


CHAVE_SPENDWISE = "sw_" + "b" * 40


def test_spendwise_desligado_sem_chave(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SPENDWISE_CHAVE=\n")
    assert carregar_spendwise(env) is None


def test_spendwise_com_url_padrao(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"SPENDWISE_CHAVE={CHAVE_SPENDWISE}\n")
    assert carregar_spendwise(env) == ("https://controle-gastos-lakes777.vercel.app", CHAVE_SPENDWISE)


def test_spendwise_url_local(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(f"SPENDWISE_CHAVE={CHAVE_SPENDWISE}\nSPENDWISE_URL=http://localhost:8000/\n")
    assert carregar_spendwise(env) == ("http://localhost:8000", CHAVE_SPENDWISE)


@pytest.mark.parametrize("chave", ["cole-aqui", "sw_curta", "cb_" + "a" * 40, "sw_" + "á" * 40])
def test_spendwise_chave_invalida(tmp_path, chave):
    env = tmp_path / ".env"
    env.write_text(f"SPENDWISE_CHAVE={chave}\n")
    with pytest.raises(ConfigError, match="começa com sw_"):
        carregar_spendwise(env)


@pytest.mark.parametrize(
    "url",
    [
        "http://exemplo.com",
        "http://localhost.qualquer.com",
        "http://127.0.0.1.nip.io",
        "ftp://exemplo.com",
        "https://",
        "https://exemplo.com/?x=1",
        "https://exemplo.com/#a",
    ],
)
def test_spendwise_recusa_url_insegura(tmp_path, url):
    env = tmp_path / ".env"
    env.write_text(f"SPENDWISE_CHAVE={CHAVE_SPENDWISE}\nSPENDWISE_URL={url}\n")
    with pytest.raises(ConfigError, match="https://"):
        carregar_spendwise(env)

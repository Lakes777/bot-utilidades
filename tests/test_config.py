import pytest

from bot_utilidades.config import ConfigError, carregar_token

TOKEN_FALSO = "123456789:" + "A" * 35


@pytest.fixture(autouse=True)
def sem_token_no_ambiente(monkeypatch):
    """Garante que o token real do seu .env nunca entre nos testes."""
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)


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

# 🤖 Bot de Utilidades para Telegram

[![Testes](https://github.com/Lakes777/bot-utilidades/actions/workflows/testes.yml/badge.svg)](https://github.com/Lakes777/bot-utilidades/actions/workflows/testes.yml)

Bot de Telegram que responde com a **cotação do Bitcoin e do dólar**, o **clima de qualquer cidade** e agenda **lembretes**. Feito em Python com `python-telegram-bot`, usando APIs públicas e gratuitas que não pedem cadastro.

<p align="center">
  <img src="docs/demo.gif" alt="Demonstração do bot no Telegram" width="320">
</p>

## Funcionalidades

| Comando | O que faz |
|---|---|
| `/bitcoin` | Preço do Bitcoin em reais, com variação, máxima e mínima do dia |
| `/dolar` | Cotação do dólar em reais, com as mesmas informações |
| `/clima Curitiba` | Temperatura, sensação térmica, umidade, vento, máxima/mínima e chance de chuva |
| `/lembrar 1h30m reunião` | Manda uma mensagem de lembrete depois do tempo pedido (`10m`, `2h`, `1h30m`, `1d`) |
| `/ajuda` | Lista os comandos |

- **Menu de comandos:** os comandos aparecem como sugestão ao digitar `/` no Telegram
- **Erros explicados:** cidade inexistente, tempo em formato inválido, API fora do ar ou sem internet geram uma mensagem clara em vez de travar o bot
- **Formato brasileiro:** valores como `R$ 433.082,00` e datas como `24/09/2026 às 20:46`

## Instalação

Requer **Python 3.10+**.

```bash
git clone https://github.com/Lakes777/bot-utilidades.git
cd bot-utilidades
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Criando o bot e guardando o token

1. No Telegram, converse com o [@BotFather](https://t.me/BotFather), mande `/newbot` e siga as instruções
2. Copie o arquivo de exemplo e cole nele o token que o BotFather te deu:

```bash
cp .env.exemplo .env
nano .env    # TELEGRAM_TOKEN=123456789:AAH...
```

> ⚠️ **O `.env` nunca vai para o Git** (está no `.gitignore`). Quem tem o token controla o bot; se ele vazar, gere outro no BotFather com `/revoke`.

## Como usar

```bash
python -m bot_utilidades
```

Com o programa rodando, abra a conversa com o seu bot no Telegram e mande `/start`. Para desligar, aperte `Ctrl+C` no terminal.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

São 61 testes cobrindo a leitura do token, as cotações, o clima, a interpretação dos lembretes e os comandos do bot. **Nenhum teste usa o token real nem acessa a internet:** as APIs são substituídas por um servidor falso (`httpx.MockTransport`) e os objetos do Telegram por imitações simples. Por isso o GitHub Actions roda tudo a cada push, nas versões 3.10 a 3.14 do Python, sem precisar de nenhum segredo.

## Estrutura do projeto

```
bot-utilidades/
├── bot_utilidades/
│   ├── __main__.py    # ponto de entrada: carrega o token e liga o bot
│   ├── config.py      # lê e valida o token do .env
│   ├── bot.py         # comandos do Telegram e agendamento dos lembretes
│   ├── cotacoes.py    # Bitcoin e dólar (AwesomeAPI)
│   ├── clima.py       # clima (Open-Meteo)
│   └── lembretes.py   # interpreta "1h30m tomar água"
├── tests/             # testes com pytest
└── .env.exemplo       # modelo do .env, sem o token de verdade
```

## Decisões técnicas

- **Lógica separada do Telegram:** `cotacoes.py`, `clima.py` e `lembretes.py` não importam nada do Telegram. Recebem dados e devolvem texto, então dá para testá-los sem bot, sem token e sem rede. O `bot.py` só liga cada comando à função certa.
- **Token protegido em três pontos:** fica no `.env` (fora do Git, e o histórico foi conferido antes do primeiro push), é validado ao iniciar (um token ausente ou ainda com o texto do exemplo gera um erro que explica como corrigir) e **não aparece nos logs**. A biblioteca `httpx` registra a URL de cada requisição, e a URL da API do Telegram contém o token, por isso o log dela fica restrito a avisos; um teste garante isso.
- **Arredondamento de verdade:** um teste mostrou que uma variação de -1,185% aparecia como -1,18%. Tanto o `Decimal` quanto o `round()` do Python usam o "arredondamento do banqueiro" (0,5 vai para o par mais próximo). Os dois foram trocados pelo arredondamento que se aprende na escola.
- **`Decimal` para dinheiro:** como no [controle de gastos](https://github.com/Lakes777/controle-gastos), os preços nunca passam por `float`, evitando erros de centavos.
- **APIs sem cadastro:** a [AwesomeAPI](https://docs.awesomeapi.com.br/api-de-moedas) (cotações) e o [Open-Meteo](https://open-meteo.com/) (clima) não pedem chave, então o token do bot é o único segredo do projeto. O clima faz duas consultas: primeiro converte o nome da cidade em coordenadas, depois busca a previsão.
- **Um handler para várias moedas:** `/bitcoin` e `/dolar` são criados pela mesma função a partir de uma descrição da moeda. Adicionar outra (Ethereum, euro) é uma linha.
- **Lembretes com limite de 7 dias:** eles ficam na memória do programa (`JobQueue`) e se perdem se o bot for desligado, então prazos longos não fariam sentido nesta versão.
- **Testes que falham quando devem:** para conferir que os testes protegem de verdade, introduzi bugs de propósito (liberar o log com o token, voltar ao arredondamento do banqueiro, mandar o lembrete para o chat errado, ignorar o limite de 7 dias, entre outros) e verifiquei que a suíte detectou cada um.

## Próximos passos

- [ ] Guardar os lembretes em SQLite, para sobreviverem a uma reinicialização
- [ ] Listar e cancelar lembretes (`/lembretes`, `/cancelar`)
- [ ] Lembretes em horário fixo (`/lembrar 18:30 ...`) e repetidos todo dia
- [ ] Alerta de preço: avisar quando o Bitcoin passar de um valor
- [ ] Hospedar o bot num servidor para ficar online 24 horas

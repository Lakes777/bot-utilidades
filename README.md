# Sidekick

[![Testes](https://github.com/Lakes777/bot-utilidades/actions/workflows/testes.yml/badge.svg)](https://github.com/Lakes777/bot-utilidades/actions/workflows/testes.yml)

**Sidekick · bot de utilidades** para o Telegram: responde com a **cotação do Bitcoin e do dólar**, o **clima de qualquer cidade** e agenda **lembretes** que ficam salvos (inclusive diários). Feito em Python com `python-telegram-bot`, usando APIs públicas e gratuitas que não pedem cadastro.

<p align="center">
  <img src="docs/demo.gif" alt="Demonstração do bot no Telegram" width="320">
</p>

## Funcionalidades

| Comando | O que faz |
|---|---|
| `/bitcoin` | Preço do Bitcoin em reais, com variação, máxima e mínima do dia |
| `/dolar` | Cotação do dólar em reais, com as mesmas informações |
| `/clima Curitiba` | Temperatura, sensação térmica, umidade, vento, máxima/mínima e chance de chuva |
| `/lembrar 1h30m reunião` | Lembrete depois do tempo pedido (`10m`, `2h`, `1h30m`, `1d`, até 365 dias) |
| `/lembrar 18:30 ligar pra mãe` | Lembrete num horário fixo: hoje, ou amanhã se o horário já passou |
| `/lembrar 25/12 20:30 ceia` | Lembrete numa data (`25/12`, `25/12/2027`, também `25/12 às 20:30`); sem horário, às 9:00 |
| `/lembrar todo dia 8:00 remédio` | Lembrete repetido todo dia no mesmo horário |
| `/lembretes` | Lista os lembretes pendentes, com número |
| `/cancelar 3` | Cancela o lembrete de número 3 (só os do próprio chat) |
| `/alerta bitcoin acima 400000` | Avisa quando o preço chegar ao valor (também `dolar abaixo 5,20`); confere a cada 5 minutos e avisa uma vez só |
| `/alertas` | Lista os alertas de preço, com número |
| `/removeralerta 2` | Apaga o alerta de número 2 (só os do próprio chat) |
| `/meuid` | Mostra o seu ID no Telegram (usado para fechar o bot, veja abaixo) |
| `/ajuda` | Lista os comandos |

- **Menu de comandos:** os comandos aparecem como sugestão ao digitar `/` no Telegram
- **Erros explicados:** cidade inexistente, tempo em formato inválido, API fora do ar ou sem internet geram uma mensagem clara em vez de travar o bot
- **Lembretes que não se perdem:** ficam salvos num banco SQLite (`dados/lembretes.db`). Se o bot for desligado, ao voltar ele reagenda tudo e manda na hora os que venceram enquanto estava fora, avisando o horário original
- **Alertas que sobrevivem a reinicializações:** ficam no mesmo banco SQLite; se o preço já passou do valor na hora de criar, o bot avisa em vez de criar um alerta que dispararia na hora
- **Horário de Brasília:** horários digitados e mostrados usam sempre o fuso `America/Sao_Paulo`, não importa o relógio do computador
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

### Deixando o bot só para você (opcional)

Qualquer pessoa que achar o bot no Telegram pode usá-lo. Para fechá-lo, mande `/meuid` para ele e coloque o número no `.env` (vários IDs separados por vírgula):

```bash
USUARIOS_PERMITIDOS=123456789,987654321
```

Quem não estiver na lista recebe "Este bot é particular" junto com o próprio ID, para poder pedir que você o libere. Com a variável vazia, o bot fica aberto para todos.

> **Atenção: o `.env` nunca vai para o Git** (está no `.gitignore`). Quem tem o token controla o bot; se ele vazar, gere outro no BotFather com `/revoke`.

## Como usar

```bash
python -m bot_utilidades
```

Com o programa rodando, abra a conversa com o seu bot no Telegram e mande `/start`. Para desligar, aperte `Ctrl+C` no terminal.

## Rodando 24 horas (Oracle Cloud)

O bot fica ligado numa máquina virtual gratuita da Oracle Cloud (Always Free, `VM.Standard.E2.1.Micro`: 1 GB de memória, Ubuntu 24.04), onde usa cerca de 45 MB. Ele roda como um serviço do **systemd**, que o liga junto com a máquina e o reinicia sozinho se ele cair:

```ini
# /etc/systemd/system/bot-utilidades.service
[Unit]
Description=Bot de utilidades do Telegram
Wants=network-online.target
After=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/bot-utilidades
ExecStart=/home/ubuntu/bot-utilidades/.venv/bin/python -m bot_utilidades
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Como foi montado: 1 GB de swap (a máquina tem só 1 GB de RAM), fuso `America/Sao_Paulo`, atualizações de segurança automáticas (`unattended-upgrades`) e acesso só por chave SSH, sem senha. O `.env` e o banco de lembretes foram copiados com `scp`, e o `.env` fica com permissão `600` (só o dono lê). Um teste reiniciando a máquina confirmou que o bot volta sozinho.

Comandos do dia a dia, a partir do PC:

```bash
ssh -i ~/.ssh/oracle_bot ubuntu@<ip> 'journalctl -u bot-utilidades -f'   # ver o log ao vivo
ssh -i ~/.ssh/oracle_bot ubuntu@<ip> 'cd bot-utilidades && git pull && sudo systemctl restart bot-utilidades'   # atualizar
```

O bot não pode rodar em dois lugares ao mesmo tempo com o mesmo token (o Telegram só entrega cada mensagem a um deles), então, com o servidor ligado, não é preciso rodar no PC.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

São 251 testes cobrindo a leitura do `.env`, as cotações, os alertas de preço, o clima, a interpretação dos lembretes (tempos, horários, datas, fuso, virada de ano), o banco SQLite (sempre num arquivo temporário) e os comandos do bot, incluindo a lista de permitidos com mensagens montadas como as que o Telegram envia. **Nenhum teste usa o token real nem acessa a internet:** as APIs são substituídas por um servidor falso (`httpx.MockTransport`) e os objetos do Telegram por imitações simples. Por isso o GitHub Actions roda tudo a cada push, nas versões 3.10 a 3.14 do Python, sem precisar de nenhum segredo.

## Estrutura do projeto

```
bot-utilidades/
├── bot_utilidades/
│   ├── __main__.py      # ponto de entrada: carrega o .env e liga o bot
│   ├── config.py        # lê e valida o token e os usuários permitidos
│   ├── bot.py           # comandos do Telegram, porteiro e agendamento dos lembretes
│   ├── cotacoes.py      # Bitcoin e dólar (AwesomeAPI)
│   ├── clima.py         # clima (Open-Meteo)
│   ├── lembretes.py     # interpreta "1h30m", "18:30", "25/12 9:00" e "todo dia 8:00"
│   └── armazenamento.py # guarda os lembretes em SQLite
├── dados/             # banco dos lembretes (criado ao rodar, fora do Git)
├── tests/             # testes com pytest
└── .env.exemplo       # modelo do .env, sem o token de verdade
```

## Decisões técnicas

- **Lógica separada do Telegram:** `cotacoes.py`, `clima.py` e `lembretes.py` não importam nada do Telegram. Recebem dados e devolvem texto, então dá para testá-los sem bot, sem token e sem rede. O `bot.py` só liga cada comando à função certa.
- **Token protegido em três pontos:** fica no `.env` (fora do Git, e o histórico foi conferido antes do primeiro push), é validado ao iniciar (um token ausente ou ainda com o texto do exemplo gera um erro que explica como corrigir) e **não aparece nos logs**. A biblioteca `httpx` registra a URL de cada requisição, e a URL da API do Telegram contém o token, por isso o log dela fica restrito a avisos; um teste garante isso.
- **Arredondamento de verdade:** um teste mostrou que uma variação de -1,185% aparecia como -1,18%. Tanto o `Decimal` quanto o `round()` do Python usam o "arredondamento do banqueiro" (0,5 vai para o par mais próximo). Os dois foram trocados pelo arredondamento que se aprende na escola.
- **`Decimal` para dinheiro:** como no [controle de gastos](https://github.com/Lakes777/controle-gastos), os preços nunca passam por `float`, evitando erros de centavos.
- **APIs sem cadastro:** a [AwesomeAPI](https://docs.awesomeapi.com.br/api-de-moedas) (cotações) e o [Open-Meteo](https://open-meteo.com/) (clima) não pedem chave. A AwesomeAPI, porém, limita as consultas sem cadastro por endereço, e da máquina da Oracle ela recusou logo a primeira (`429 Quota exceeded`), enquanto do PC respondia normalmente: IPs de nuvem são compartilhados. Por isso o `.env` aceita uma chave gratuita opcional (`AWESOMEAPI_TOKEN`, 100 mil consultas por mês), enviada no cabeçalho `x-api-key` e só nas requisições de cotação, para não aparecer em URLs nem ir para a API do clima. O clima faz duas consultas: primeiro converte o nome da cidade em coordenadas, depois busca a previsão.
- **Um handler para várias moedas:** `/bitcoin` e `/dolar` são criados pela mesma função a partir de uma descrição da moeda. Adicionar outra (Ethereum, euro) é uma linha.
- **Banco como fonte da verdade, `JobQueue` só como despertador:** cada lembrete é salvo no SQLite e o agendador guarda só o número dele. Na hora de enviar, o texto é lido do banco; um lembrete cancelado no meio do caminho simplesmente não é achado. O lembrete só é apagado **depois** que o Telegram confirma o envio: se a internet cair, ele continua salvo e sai quando o bot voltar. Datas ficam em UTC, sempre no mesmo formato de texto, para a ordem alfabética ser a cronológica.
- **Lembrete atrasado não se perde:** por padrão, o agendador (APScheduler) descarta em silêncio um job que dispara com mais de 1 segundo de atraso, o que aconteceria com o PC hibernando ou com lembretes vencidos com o bot desligado. Confirmei isso com o agendador de verdade (um job 3 horas atrasado foi descartado) e desliguei o limite (`misfire_grace_time=None`).
- **Diário conta a partir de agora:** depois de cada envio, o próximo é marcado para a próxima vez que o relógio chegar ao horário. Se o bot ficou 3 dias desligado, sai uma mensagem só, e não três.
- **"18:30" é horário, "18h" é duração:** só o formato com dois-pontos vira horário fixo, porque `/lembrar 18h ...` já queria dizer "daqui a 18 horas".
- **Cancelar só o que é seu:** o `/cancelar` filtra pelo chat no próprio SQL, então chutar números não apaga lembretes de outra pessoa. Os números usam `AUTOINCREMENT` para nunca serem reaproveitados.
- **Porteiro antes dos comandos:** a lista de permitidos é um handler que roda num grupo anterior ao de todos os comandos e interrompe o processamento (`ApplicationHandlerStop`) de quem não está nela. Assim nenhum comando novo fica aberto por esquecimento. O `/meuid` roda num grupo ainda anterior, para funcionar para qualquer pessoa.
- **Alertas com uma consulta por moeda:** a cada 5 minutos, o bot junta os alertas de todos os chats, busca cada moeda uma vez só (e não uma vez por alerta, o que esbarraria no limite da API gratuita) e confere cada alerta com esse preço. O alerta é apagado depois de enviado, senão repetiria a mensagem a cada 5 minutos enquanto o preço ficasse do outro lado; se o envio falhar por falta de internet, ele continua salvo para a próxima conferência.
- **Valor digitado do jeito brasileiro:** `400.000`, `400.000,50` e `5,20` são entendidos; um ponto seguido de exatamente três dígitos é de milhar, qualquer outro separa os centavos (`5.20`). Notação científica (`1e30`) é recusada, e um valor mais de 10 vezes longe do preço atual pede confirmação: no dólar, `5.500` viraria R$ 5.500 e o alerta nunca dispararia.
- **Alertas também respeitam a lista de permitidos:** o porteiro só filtra mensagens recebidas, e os avisos são enviados pelo agendador. Por isso a conferência apaga os alertas de quem não está mais na lista, senão um estranho que criou alertas com o bot aberto continuaria recebendo avisos.
- **Apagar antes de enviar:** o alerta é apagado logo antes do envio; se o usuário o removeu enquanto a cotação era buscada, o aviso não sai. Se o envio falhar por rede, ele volta com o mesmo número; se o chat bloqueou o bot ou não existe mais, fica apagado.
- **Testes que falham quando devem:** para conferir que os testes protegem de verdade, introduzi bugs de propósito (liberar o log com o token, voltar ao arredondamento do banqueiro, mandar o lembrete para o chat errado, cancelar lembrete de outro chat, reagendar o diário a partir do horário antigo, deixar o porteiro passar, entre outros) e verifiquei que a suíte detectou cada um.

## Próximos passos

- [x] Guardar os lembretes em SQLite, para sobreviverem a uma reinicialização
- [x] Listar e cancelar lembretes (`/lembretes`, `/cancelar`)
- [x] Lembretes em horário fixo (`/lembrar 18:30 ...`) e repetidos todo dia
- [x] Lista de usuários permitidos no `.env`
- [x] Alerta de preço: avisar quando o Bitcoin (ou o dólar) chegar a um valor
- [x] Hospedar o bot num servidor para ficar online 24 horas (Oracle Cloud, systemd)
- [x] Lembretes numa data específica (`/lembrar 25/12 9:00 ...`)
- [ ] Lembretes semanais num dia da semana e horário escolhidos (`/lembrar toda quinta 19:00 ...`)

"""Monta o bot: liga cada comando do Telegram à função que responde."""

import logging
from datetime import datetime, timedelta

import httpx
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    JobQueue,
    TypeHandler,
)

from bot_utilidades import alertas, clima, cotacoes, lembretes
from bot_utilidades.armazenamento import Banco, Lembrete

log = logging.getLogger(__name__)

# Um lembrete entregue com mais atraso que isso ganha um aviso (o bot estava desligado).
TOLERANCIA_ATRASO = timedelta(minutes=1)

# Botões embaixo de cada lembrete: o que vai no callback_data e quanto adiar.
ADIAMENTOS = {"adiar10": timedelta(minutes=10), "adiar60": timedelta(hours=1)}

# Aparecem no menu "/" do Telegram e na mensagem de /ajuda.
COMANDOS = [
    BotCommand("bitcoin", "preço do Bitcoin em reais"),
    BotCommand("dolar", "cotação do dólar"),
    BotCommand("clima", "clima agora, ex.: /clima Curitiba"),
    BotCommand(
        "lembrar", "lembrete, ex.: /lembrar 10m, 18:30, 25/12 9:00, todo dia 8:00, toda seg e qua 19:00"
    ),
    BotCommand("lembretes", "lista seus lembretes pendentes"),
    BotCommand("cancelar", "cancela um lembrete, ex.: /cancelar 3"),
    BotCommand("alerta", "avisa quando o preço chegar, ex.: /alerta bitcoin acima 400000"),
    BotCommand("alertas", "lista seus alertas de preço"),
    BotCommand("removeralerta", "apaga um alerta, ex.: /removeralerta 2"),
    BotCommand("meuid", "mostra seu ID no Telegram"),
    BotCommand("ajuda", "lista de comandos"),
]

AJUDA = "Comandos disponíveis:\n" + "\n".join(
    f"/{c.command} - {c.description}" for c in COMANDOS
)


async def meuid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    usuario_id = update.effective_user.id
    texto = f"Seu ID no Telegram é {usuario_id}."
    if context.bot_data["permitidos"] is None:
        texto += (
            "\n\nPara deixar o bot só para você, coloque no .env:\n"
            f"USUARIOS_PERMITIDOS={usuario_id}"
        )
    await update.message.reply_text(texto)
    # Responde a qualquer pessoa e para por aqui, sem passar pelo porteiro.
    raise ApplicationHandlerStop


async def porteiro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roda antes de todos os comandos e barra quem não está em USUARIOS_PERMITIDOS."""
    permitidos = context.bot_data["permitidos"]
    usuario = update.effective_user
    if permitidos is None or (usuario and usuario.id in permitidos):
        return  # segue para o comando normalmente

    log.info("Usuário %s barrado", usuario.id if usuario else "desconhecido")
    if update.callback_query:
        # Clique num botão: sem answer(), o botão fica girando no celular da pessoa.
        await update.callback_query.answer("🔒 Este bot é particular.")
    elif update.effective_message and usuario:
        await update.effective_message.reply_text(
            "🔒 Este bot é particular.\n"
            f"Seu ID é {usuario.id}. Se você conhece o dono, mande esse número "
            "para ele te liberar."
        )
    # Interrompe o processamento: os comandos (grupo 0) nem chegam a rodar.
    raise ApplicationHandlerStop


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    nome = update.effective_user.first_name
    await update.message.reply_text(
        f"Olá, {nome}! Eu sou o Sidekick, seu bot de utilidades.\n\n{AJUDA}"
    )


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(AJUDA)


async def buscar_cotacao(context: ContextTypes.DEFAULT_TYPE, moeda: cotacoes.Moeda) -> cotacoes.Cotacao:
    """Busca a cotação com o cliente HTTP e a chave da API guardados no bot."""
    return await cotacoes.buscar(
        moeda, context.bot_data["http"], chave=context.bot_data.get("chave_cotacoes")
    )


def responder_cotacao(moeda: cotacoes.Moeda):
    """Cria o handler de um comando de cotação (/bitcoin, /dolar...)."""

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            texto = cotacoes.formatar(await buscar_cotacao(context, moeda))
        except cotacoes.CotacaoError as erro:
            texto = f"⚠️ {erro}"
        await update.message.reply_text(texto)

    return handler


async def responder_clima(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # context.args são as palavras depois do comando: ["São", "Paulo"]
    nome = " ".join(context.args)
    if not nome:
        await update.message.reply_text("Diga a cidade, ex.: /clima Curitiba")
        return
    try:
        texto = clima.formatar(await clima.buscar(nome, context.bot_data["http"]))
    except clima.ClimaError as erro:
        texto = f"⚠️ {erro}"
    await update.message.reply_text(texto)


def agora() -> datetime:
    """Data e hora atuais em Brasília. Os testes trocam esta função."""
    return datetime.now(lembretes.FUSO)


def agendar(job_queue: JobQueue, lembrete: Lembrete) -> None:
    """Pede ao JobQueue para chamar enviar_lembrete() na hora do lembrete."""
    job_queue.run_once(
        enviar_lembrete,
        when=lembrete.quando,
        chat_id=lembrete.chat_id,
        data=lembrete.id,  # só o número: o texto é lido do banco na hora de enviar
        name=f"lembrete-{lembrete.id}",
        # Por padrão, um job que dispara com mais de 1 s de atraso (PC hibernando,
        # por exemplo) é descartado em silêncio. None = mandar mesmo atrasado.
        # Isso também faz os lembretes vencidos com o bot desligado saírem na hora.
        job_kwargs={"misfire_grace_time": None},
    )


async def lembrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    banco: Banco = context.bot_data["banco"]
    chat_id = update.effective_chat.id
    hora = agora()
    try:
        pedido = lembretes.interpretar(context.args, hora)
    except lembretes.LembreteError as erro:
        await update.message.reply_text(f"⚠️ {erro}")
        return

    if banco.contar(chat_id) >= lembretes.LIMITE_POR_CHAT:
        await update.message.reply_text(
            f"⚠️ Você já tem {lembretes.LIMITE_POR_CHAT} lembretes pendentes. "
            "Cancele algum com /cancelar."
        )
        return

    lembrete = banco.adicionar(
        chat_id,
        pedido.texto,
        pedido.quando,
        diario=pedido.diario,
        semanal=pedido.semanal,
        dias=pedido.dias,
        dia_do_mes=pedido.dia_do_mes,
    )
    agendar(context.job_queue, lembrete)
    await update.message.reply_text(lembretes.confirmar(pedido, hora))


async def enviar_lembrete(context: ContextTypes.DEFAULT_TYPE) -> None:
    banco: Banco = context.bot_data["banco"]
    lembrete = banco.buscar(context.job.data)
    if lembrete is None:  # foi apagado enquanto esperava
        return

    hora = agora()
    if hora - lembrete.quando > TOLERANCIA_ATRASO:
        horario = lembretes.data_e_hora(lembrete.quando, hora)
        mensagem = f"⏰ Lembrete atrasado (era para {horario}): {lembrete.texto}"
    else:
        mensagem = f"⏰ Lembrete: {lembrete.texto}"

    if lembrete.repete:
        mensagem += f"\n({repeticao(lembrete)}; para parar: /cancelar {lembrete.id})"

    # Registra antes de enviar, porque o número vai dentro dos botões.
    enviado = banco.registrar_envio(lembrete.chat_id, lembrete.texto, hora)
    try:
        await context.bot.send_message(
            lembrete.chat_id, mensagem, reply_markup=botoes_do_lembrete(enviado.id)
        )
    except Forbidden:
        # A pessoa bloqueou o bot: não adianta tentar de novo a cada reinício.
        log.warning("Chat %s bloqueou o bot; lembrete %s apagado", lembrete.chat_id, lembrete.id)
        banco.esquecer_envio(enviado.id)
        banco.remover(lembrete.id)
        return
    except Exception:
        banco.esquecer_envio(enviado.id)
        raise

    # Só mexe no banco depois de enviar: se a internet cair no envio, o erro sobe,
    # o lembrete continua como estava e sai quando o bot for reiniciado.
    if lembrete.repete:
        # Conta a partir de agora, não do horário antigo: se o bot ficou dias
        # desligado, o lembrete sai uma vez só em vez de um por dia (ou semana) perdido.
        quando = lembrete.quando.astimezone(lembretes.FUSO)
        if lembrete.dia_do_mes is not None:
            proxima = lembretes.proxima_vez_no_mes(lembrete.dia_do_mes, quando.time(), hora)
        elif lembrete.semanal:
            proxima = lembretes.proxima_vez_nos_dias(lembrete.dias, quando.time(), hora)
        else:
            proxima = lembretes.proxima_vez(quando.time(), hora)
        agendar(context.job_queue, banco.adiar(lembrete.id, proxima))
    else:
        banco.remover(lembrete.id)


def botoes_do_lembrete(enviado_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Adiar 10 min", callback_data=f"adiar10:{enviado_id}"),
                InlineKeyboardButton("Adiar 1 h", callback_data=f"adiar60:{enviado_id}"),
                InlineKeyboardButton("Feito", callback_data=f"feito:{enviado_id}"),
            ]
        ]
    )


async def responder_botao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clique em "Adiar 10 min", "Adiar 1 h" ou "Feito" embaixo de um lembrete."""
    consulta = update.callback_query
    banco: Banco = context.bot_data["banco"]
    acao, _, numero = (consulta.data or "").partition(":")
    if (acao not in ADIAMENTOS and acao != "feito") or not numero.isdecimal():
        await consulta.answer()
        return

    chat_id = update.effective_chat.id
    enviado = banco.buscar_envio(int(numero), chat_id)
    if enviado is None:
        await consulta.answer("Esse lembrete já foi respondido ou é antigo demais.")
        await editar_mensagem(consulta, None)
        return
    if acao in ADIAMENTOS and banco.contar(chat_id) >= lembretes.LIMITE_POR_CHAT:
        # O botão continua valendo: dá para tentar de novo depois de um /cancelar.
        await consulta.answer(
            f"Você já tem {lembretes.LIMITE_POR_CHAT} lembretes pendentes.", show_alert=True
        )
        return

    # Cada botão vale uma vez: se dois cliques chegarem juntos, só um tira o registro.
    if banco.tirar_envio(enviado.id, chat_id) is None:
        await consulta.answer("Esse lembrete já foi respondido.")
        return

    if acao == "feito":
        await consulta.answer("Feito!")
        await editar_mensagem(consulta, "✅ Feito")
        return

    hora = agora()
    try:
        novo = banco.adicionar(chat_id, enviado.texto, hora + ADIAMENTOS[acao])
        agendar(context.job_queue, novo)
    except Exception:
        await consulta.answer("Não consegui adiar. Tente /lembrar.")
        raise
    quando = lembretes.descrever_horario(novo.quando, hora)
    await consulta.answer(f"Adiado {quando}")
    await editar_mensagem(consulta, f"💤 Adiado {quando} (#{novo.id})")


async def editar_mensagem(consulta, nota: str | None) -> None:
    """Tira os botões da mensagem do lembrete e, se houver nota, escreve embaixo.

    A edição é só enfeite: se a mensagem foi apagada ou já está sem botões
    (dois cliques rápidos), o Telegram recusa e o bot só registra no log.
    """
    mensagem = consulta.message
    try:
        if nota is None or not isinstance(getattr(mensagem, "text", None), str):
            await consulta.edit_message_reply_markup(reply_markup=None)
        else:
            await consulta.edit_message_text(f"{mensagem.text}\n{nota}")
    except (BadRequest, TypeError) as erro:
        log.info("Não deu para editar a mensagem do lembrete: %s", erro)


def repeticao(lembrete: Lembrete) -> str:
    """"todo dia", "toda quinta" ou "todo dia 10", conforme o lembrete repetido."""
    if lembrete.dia_do_mes is not None:
        return f"todo mês, no dia {lembrete.dia_do_mes}"
    if lembrete.semanal:
        return lembretes.toda_semana(lembrete.dias)
    return "todo dia"


def descrever_quando(lembrete: Lembrete, hora: datetime) -> str:
    if lembrete.repete:
        virgula = "," if lembrete.dia_do_mes is not None else ""  # "todo mês, no dia 10, às 9:00"
        horario = lembrete.quando.astimezone(lembretes.FUSO)
        return f"{repeticao(lembrete)}{virgula} às {horario:%H:%M}"
    return lembretes.descrever_horario(lembrete.quando, hora)


async def listar_lembretes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pendentes = context.bot_data["banco"].do_chat(update.effective_chat.id)
    if not pendentes:
        await update.message.reply_text(
            "Você não tem lembretes pendentes.\nCrie um com /lembrar 10m tomar água"
        )
        return
    hora = agora()
    linhas = [
        f"#{l.id} {descrever_quando(l, hora)}: {lembretes.encurtar(l.texto)}" for l in pendentes
    ]
    await update.message.reply_text(
        "Seus lembretes:\n" + "\n".join(linhas) + "\n\nPara cancelar: /cancelar número"
    )


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        numero = lembretes.ler_numero(context.args)
    except lembretes.LembreteError as erro:
        await update.message.reply_text(f"⚠️ {erro}")
        return

    # Filtrar pelo chat impede que alguém cancele o lembrete de outra pessoa chutando números.
    lembrete = context.bot_data["banco"].cancelar(numero, update.effective_chat.id)
    if lembrete is None:
        await update.message.reply_text(
            f"⚠️ Não achei o lembrete #{numero}. Veja os seus em /lembretes"
        )
        return

    # Tira do agendador também (se sobrasse, enviar_lembrete não acharia nada no banco).
    for job in context.job_queue.get_jobs_by_name(f"lembrete-{lembrete.id}"):
        job.schedule_removal()
    await update.message.reply_text(f"🗑️ Lembrete #{lembrete.id} cancelado: {lembrete.texto}")


async def criar_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    banco: Banco = context.bot_data["banco"]
    chat_id = update.effective_chat.id
    try:
        pedido = alertas.interpretar(context.args)
    except alertas.AlertaError as erro:
        await update.message.reply_text(f"⚠️ {erro}")
        return

    if len(banco.alertas_do_chat(chat_id)) >= alertas.LIMITE_POR_CHAT:
        await update.message.reply_text(
            f"⚠️ Você já tem {alertas.LIMITE_POR_CHAT} alertas. Apague algum com /removeralerta."
        )
        return

    moeda = pedido.moeda
    descricao = alertas.descrever(moeda, pedido.direcao, pedido.valor)
    try:
        preco = (await buscar_cotacao(context, moeda)).preco
    except cotacoes.CotacaoError:
        preco = None  # sem a cotação agora, salva mesmo assim: a conferência tenta depois

    if preco is not None and alertas.longe_demais(pedido.valor, preco):
        await update.message.reply_text(
            f"⚠️ Entendi {cotacoes.reais(pedido.valor, moeda.casas)}, mas o {moeda.nome} está em "
            f"{cotacoes.reais(preco, moeda.casas)}: é mais de {alertas.DISTANCIA_MAXIMA} vezes "
            "de diferença. Confira o valor (a vírgula separa os centavos: 5,20)."
        )
        return

    # Um alerta que já está atingido dispararia na primeira conferência: melhor avisar já.
    if preco is not None and alertas.atingiu(pedido.direcao, pedido.valor, preco):
        await update.message.reply_text(
            f"⚠️ O {moeda.nome} já está {pedido.direcao} desse valor: "
            f"agora está em {cotacoes.reais(preco, moeda.casas)}. Escolha outro valor."
        )
        return

    alerta = banco.adicionar_alerta(chat_id, moeda.par, pedido.direcao, pedido.valor)
    texto = f"✅ Alerta #{alerta.id} criado: {descricao}."
    if preco is not None:
        texto += f"\nAgora está em {cotacoes.reais(preco, moeda.casas)}."
    minutos = int(alertas.INTERVALO.total_seconds() // 60)
    texto += f"\nConfiro a cada {minutos} minutos e aviso uma vez só."
    await update.message.reply_text(texto)


async def listar_alertas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pendentes = context.bot_data["banco"].alertas_do_chat(update.effective_chat.id)
    if not pendentes:
        await update.message.reply_text(
            "Você não tem alertas.\nCrie um com /alerta bitcoin acima 400000"
        )
        return
    linhas = [
        f"#{a.id} {alertas.descrever(alertas.POR_PAR[a.par], a.direcao, a.valor)}"
        for a in pendentes
    ]
    await update.message.reply_text(
        "Seus alertas:\n" + "\n".join(linhas) + "\n\nPara apagar: /removeralerta número"
    )


async def remover_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        numero = lembretes.ler_numero(context.args)
    except lembretes.LembreteError:
        await update.message.reply_text("Diga o número do alerta, ex.: /removeralerta 2\nVeja os seus em /alertas")
        return
    alerta = context.bot_data["banco"].cancelar_alerta(numero, update.effective_chat.id)
    if alerta is None:
        await update.message.reply_text(f"⚠️ Não achei o alerta #{numero}. Veja os seus em /alertas")
        return
    descricao = alertas.descrever(alertas.POR_PAR[alerta.par], alerta.direcao, alerta.valor)
    await update.message.reply_text(f"🗑️ Alerta #{alerta.id} apagado: {descricao}")


async def conferir_alertas(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roda a cada INTERVALO: busca cada moeda uma vez e avisa os alertas atingidos.

    Cada alerta avisa uma vez só e é apagado, senão mandaria a mesma mensagem a
    cada 5 minutos enquanto o preço ficasse do outro lado.
    """
    banco: Banco = context.bot_data["banco"]
    permitidos = context.bot_data.get("permitidos")
    pendentes = []
    for alerta in banco.todos_alertas():
        # O porteiro só filtra mensagens recebidas; quem saiu da lista de permitidos
        # (ou criou alertas quando o bot era aberto) não recebe mais avisos.
        if permitidos is not None and alerta.chat_id not in permitidos:
            banco.remover_alerta(alerta.id)
        else:
            pendentes.append(alerta)
    if not pendentes:
        return

    precos = {}
    for par in {a.par for a in pendentes}:
        moeda = alertas.POR_PAR[par]
        try:
            precos[par] = (await buscar_cotacao(context, moeda)).preco
        except cotacoes.CotacaoError as erro:
            log.warning("Sem cotação de %s para os alertas: %s", moeda.nome, erro)

    for alerta in pendentes:
        preco = precos.get(alerta.par)
        if preco is None or not alertas.atingiu(alerta.direcao, alerta.valor, preco):
            continue
        # Apaga antes de enviar: se o usuário apagou o alerta enquanto a cotação
        # era buscada, remover_alerta devolve False e o aviso não sai.
        if not banco.remover_alerta(alerta.id):
            continue
        moeda = alertas.POR_PAR[alerta.par]
        try:
            await context.bot.send_message(
                alerta.chat_id, alertas.aviso(moeda, alerta.direcao, alerta.valor, preco)
            )
        except (Forbidden, BadRequest) as erro:
            # Bloqueou o bot ou o chat não existe mais: tentar de novo não adianta.
            log.warning("Alerta %s apagado sem enviar (chat %s): %s", alerta.id, alerta.chat_id, erro)
        except Exception:
            # Falha de rede no envio: o alerta volta e é conferido de novo na próxima vez.
            log.exception("Falha ao enviar o alerta %s", alerta.id)
            banco.restaurar_alerta(alerta)


async def preparar(app: Application) -> None:
    # Um único cliente HTTP reaproveita conexões entre os comandos.
    app.bot_data["http"] = httpx.AsyncClient()
    await app.bot.set_my_commands(COMANDOS)
    reagendar(app)
    app.job_queue.run_repeating(
        conferir_alertas, interval=alertas.INTERVALO, first=30, name="conferir-alertas"
    )


def reagendar(app: Application) -> None:
    """Agenda de novo os lembretes salvos (os vencidos saem na hora)."""
    pendentes = app.bot_data["banco"].todos()
    for lembrete in pendentes:
        agendar(app.job_queue, lembrete)
    log.info("%d lembrete(s) reagendado(s)", len(pendentes))


async def fechar_http(app: Application) -> None:
    await app.bot_data["http"].aclose()


def criar_app(
    token: str,
    banco: Banco,
    permitidos: frozenset[int] | None = None,
    chave_cotacoes: str | None = None,
) -> Application:
    app = (
        Application.builder()
        .token(token)
        .post_init(preparar)
        .post_shutdown(fechar_http)
        .build()
    )
    app.bot_data["banco"] = banco
    app.bot_data["permitidos"] = permitidos
    app.bot_data["chave_cotacoes"] = chave_cotacoes
    # Os grupos rodam em ordem (-2, -1, 0...). /meuid vem antes do porteiro para
    # funcionar para qualquer pessoa; o porteiro vem antes de todos os comandos.
    app.add_handler(CommandHandler("meuid", meuid), group=-2)
    app.add_handler(TypeHandler(Update, porteiro), group=-1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("bitcoin", responder_cotacao(cotacoes.BITCOIN)))
    app.add_handler(CommandHandler("dolar", responder_cotacao(cotacoes.DOLAR)))
    app.add_handler(CommandHandler("clima", responder_clima))
    app.add_handler(CommandHandler("lembrar", lembrar))
    app.add_handler(CommandHandler("lembretes", listar_lembretes))
    app.add_handler(CommandHandler("cancelar", cancelar))
    app.add_handler(CallbackQueryHandler(responder_botao))
    app.add_handler(CommandHandler("alerta", criar_alerta))
    app.add_handler(CommandHandler("alertas", listar_alertas))
    app.add_handler(CommandHandler("removeralerta", remover_alerta))
    return app


def configurar_logs() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    # O httpx registra cada requisição com a URL completa, que contém o token.
    # Subir o nível dele para WARNING evita que o token apareça no terminal.
    logging.getLogger("httpx").setLevel(logging.WARNING)

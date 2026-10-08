"""Console do RPA Simba: dashboard, tarefas (lista do Bacen x ServiceNow) com seleção e play, e configuração.

Sem base de dados: o ServiceNow é a fonte de verdade da execução e a lista do Bacen (SIMBA_LISTA_BACEN) a fonte do
que precisa ser respondido. "Baixar casos" grava um retrato do ServiceNow (JSON) que só muda quando o usuário clica;
o play dispara o runner em outro processo, que grava o andamento num arquivo que o console lê.
"""
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil
from nicegui import run, ui

from simba import andamento, chaves, config, consulta, lista_bacen
from simba.servicenow import ServiceNow

RAIZ = Path(__file__).resolve().parents[1]
SELECIONAVEIS = ("Pendente", "Falha")

COLUNAS = [
    ("ccs", "Requisição CCS", 190),
    ("sistema", "Envio", 80),
    ("limite", "Prazo", 105),
    ("prazo", "Situação do prazo", 130),
    ("simba_code", "Atendimento Simba", 175),
    ("judtask", "JUDTASK", 140),
    ("situacao", "Situação", 125),
    ("validado", "Validado", 95),
    ("transmitido", "Transmitido", 110),
    ("cabine", "Cabine", 85),
    ("categoria_erro", "Categoria do erro", 160),
    ("erro", "Erro", 420),
    ("tentativas", "Tent.", 75),
    ("jud", "JUD", 120),
    ("oficio", "Ofício (JUD)", 190),
    ("tipo", "Tipo", 105),
    ("instituicao", "Instituição", 200),
    ("processo", "Processo", 190),
    ("vara", "Vara", 90),
    ("investigados", "Invest.", 85),
    ("na_lista", "Na lista", 90),
    ("atualizado_em", "Atualizado (UTC)", 160),
]


# --- dados ------------------------------------------------------------------------


def carregar_linhas() -> tuple[Optional[dict], Optional[dict], list[consulta.Linha]]:
    """(retrato do ServiceNow, lista do Bacen, linhas cruzadas)."""
    retrato = consulta.carregar(consulta.arquivo_padrao())
    lista = lista_bacen.carregar()
    return retrato, lista, consulta.montar_linhas(retrato, lista["requisicoes"] if lista else [])


def baixar_casos() -> None:
    sn = ServiceNow(config.SN_INSTANCIA, config.SN_USUARIO, config.SN_SENHA)
    consulta.salvar(consulta.baixar(sn), consulta.arquivo_padrao())


def runner_rodando(estado: Optional[dict]) -> bool:
    return bool(estado and estado.get("situacao") in ("rodando", "parando") and psutil.pid_exists(estado["pid"]))


def checar_lote(linhas: list[dict], simular: bool) -> tuple[list[str], list[str]]:
    """(bloqueios, avisos) antes do play."""
    bloqueios, avisos = [], []
    if runner_rodando(andamento.ler()):
        bloqueios.append("Já há um lote em execução. Aguarde terminar ou peça a parada.")
    for exe in (config.SIMBA_EXE, config.TRANSMISSOR_EXE):
        if not exe.is_file():
            bloqueios.append(f"Simba não encontrado: {exe} (confira o .env)")
    repetidos = [a for a, n in Counter(l["simba_code"] for l in linhas).items() if n > 1 and a]
    if repetidos:
        bloqueios.append(f"Mais de um caso para o mesmo atendimento no lote: {', '.join(repetidos)}")
    por_orgao = Counter(chaves.orgao_do_atendimento(l["simba_code"]) for l in linhas if l["simba_code"])
    for orgao, casos in sorted(por_orgao.items()):
        try:
            chaves.da_orgao(orgao)
        except chaves.ChaveIndisponivel as erro:
            if simular:
                avisos.append(f"{erro} — na simulação a seleção da chave é pulada ({casos} caso(s))")
            else:
                avisos.append(f"{erro} — {casos} caso(s) vão falhar como ação manual")
    return bloqueios, avisos


def disparar(linhas: list[dict], simular: bool) -> Path:
    """Grava a lista e inicia o runner em outro processo (segue rodando mesmo se o console fechar)."""
    agora = f"{datetime.now():%Y%m%d-%H%M%S}"
    lista = config.CONSOLE_DIR / "lotes" / f"lote_{agora}.json"
    lista.parent.mkdir(parents=True, exist_ok=True)
    lista.write_text(json.dumps(list(dict.fromkeys(l["work_item"] for l in linhas))), encoding="utf-8")
    log = lista.with_suffix(".log")
    comando = [sys.executable, "-m", "simba.runner", "--lista", str(lista)] + (["--simular"] if simular else [])
    with log.open("w", encoding="utf-8") as saida:
        subprocess.Popen(
            comando,
            cwd=RAIZ,
            stdout=saida,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    return lista


# --- partes comuns ------------------------------------------------------------------


def cabecalho(titulo: str) -> None:
    with ui.header().classes("items-center justify-between bg-slate-800"):
        with ui.row().classes("items-center gap-6"):
            ui.label("Simba RPA").classes("text-lg font-bold")
            ui.link("Dashboard", "/").classes("text-white")
            ui.link("Tarefas", "/tarefas").classes("text-white")
            ui.link("Configuração", "/configuracao").classes("text-white")
        ui.label(titulo).classes("text-sm opacity-80")


def barra_dados(retrato: Optional[dict], lista: Optional[dict]) -> None:
    with ui.row().classes("w-full items-center gap-2"):
        ui.button("Baixar casos do ServiceNow", icon="cloud_download", on_click=acao_baixar)
        ui.button("Exportar Excel", icon="download", on_click=acao_exportar).props("outline")
        if retrato:
            desde = retrato.get("itens_desde") or "todas as datas"
            ui.label(f"ServiceNow: {retrato['baixado_em'].replace('T', ' ')} · work items desde {desde}").classes(
                "text-sm text-gray-500"
            )
        else:
            ui.label("Nenhum retrato do ServiceNow baixado ainda.").classes("text-sm text-orange-600")
        if lista:
            ui.label(f"Lista do Bacen: {len(lista['requisicoes']):,} requisições".replace(",", ".")).classes(
                "text-sm text-gray-500"
            )
        else:
            ui.label(f"Lista do Bacen não encontrada: {config.LISTA_BACEN} (SIMBA_LISTA_BACEN)").classes(
                "text-sm text-orange-600"
            )


async def acao_baixar() -> None:
    if runner_rodando(andamento.ler()):
        # Console e runner têm limitadores separados: juntos passariam do limite de 100 requisições/minuto.
        ui.notify("Há um lote em execução: baixe os casos quando ele terminar (limite de requisições do ServiceNow)",
                  type="warning", multi_line=True)
        return
    aviso = ui.notification("Baixando casos do ServiceNow...", spinner=True, timeout=None)
    try:
        await run.io_bound(baixar_casos)
    except Exception as erro:
        aviso.dismiss()
        ui.notify(f"Falha ao baixar: {erro}", type="negative", multi_line=True, timeout=0, close_button=True)
        return
    aviso.dismiss()
    ui.navigate.reload()


def acao_exportar() -> None:
    retrato, _, linhas = carregar_linhas()
    if not linhas:
        ui.notify("Nada para exportar: baixe os casos e confira a lista do Bacen", type="warning")
        return
    destino = config.CONSOLE_DIR / "exportacoes" / f"simba_{datetime.now():%Y%m%d-%H%M%S}.xlsx"
    consulta.exportar(linhas, destino, retrato["baixado_em"] if retrato else "não baixado")
    ui.download.file(destino)


def painel_execucao() -> None:
    @ui.refreshable
    def conteudo() -> None:
        estado = andamento.ler()
        if not estado:
            ui.label("Nenhum lote executado ainda.").classes("text-gray-500")
            return
        rodando = runner_rodando(estado)
        situacao = estado["situacao"] if rodando or estado["situacao"] not in ("rodando", "parando") else "interrompido"
        with ui.row().classes("items-center gap-4"):
            cor = {"rodando": "green", "parando": "orange", "encerrado": "blue"}.get(situacao, "red")
            ui.badge(situacao.upper(), color=cor)
            if estado.get("simulacao"):
                ui.badge("SIMULAÇÃO (nada é gravado nem enviado)", color="purple")
            ui.label(f"{estado['concluidos']} de {estado['total']} casos · {estado.get('por_minuto', 0)} por minuto")
            restantes = estado["total"] - estado["concluidos"]
            if rodando and estado.get("por_minuto"):
                ui.label(f"previsão: ~{restantes / estado['por_minuto']:.0f} min").classes("text-gray-500")
            if rodando and situacao == "rodando":
                ui.button("Parar após o caso atual", icon="stop", color="red", on_click=parar).props("outline dense")
        ui.linear_progress(estado["concluidos"] / max(estado["total"], 1), show_value=False).classes("w-full")
        if estado.get("atual"):
            atual = estado["atual"]
            ui.label(f"Em execução: {atual['judtask']} · {atual['atendimento']} · {atual['etapa']}").classes("text-sm")
        if estado.get("erro"):
            ui.label(f"Lote interrompido: {estado['erro']}").classes("text-sm text-red-600")
        for judtask, caso in list(estado["casos"].items())[-6:][::-1]:
            cor = "text-green-700" if caso["situacao"] == "Sucesso" else "text-red-700"
            ui.label(f"{caso['fim'][11:]} · {judtask} · {caso['situacao']} · {caso['mensagem'][:160]}").classes(
                f"text-xs {cor}"
            )

    def parar() -> None:
        andamento.pedir_parada()
        ui.notify("Parada pedida: o caso em andamento termina e o lote encerra", type="warning")

    with ui.card().classes("w-full"):
        ui.label("Execução").classes("text-base font-bold")
        conteudo()
    ui.timer(3, conteudo.refresh)


def cartao(titulo: str, valor: int, cor: str = "") -> None:
    with ui.card().classes("min-w-40"):
        ui.label(titulo).classes("text-xs text-gray-500")
        ui.label(f"{valor:,}".replace(",", ".")).classes(f"text-2xl font-bold {cor}")


# --- páginas ------------------------------------------------------------------------


@ui.page("/")
def dashboard() -> None:
    cabecalho("Dashboard")
    retrato, lista, linhas = carregar_linhas()
    barra_dados(retrato, lista)
    resumo = consulta.resumo(linhas)
    with ui.row().classes("w-full gap-4"):
        for nome, valor in resumo.items():
            cor = "text-red-700" if nome in ("Com erro", "Vencidas sem transmissão") and valor else ""
            cartao(nome, valor, cor)
    total = resumo["Requisições"] or 1
    with ui.card().classes("w-full"):
        ui.label("Funil da lista do Bacen (envio pelo Simba)" if lista else "Funil dos work items").classes(
            "text-base font-bold"
        )
        for etapa in ("Com work item", "Validados", "Transmitidos", "Cabine"):
            with ui.row().classes("w-full items-center"):
                ui.label(etapa).classes("w-32")
                ui.linear_progress(resumo[etapa] / total, show_value=False).classes("flex-1")
                ui.label(f"{resumo[etapa]:,} ({resumo[etapa] / total:.0%})".replace(",", ".")).classes("w-32 text-right")
    painel_execucao()
    erros = Counter((l.categoria_erro, l.erro[:200]) for l in linhas if l.categoria_erro)
    with ui.card().classes("w-full"):
        ui.label("Erros mais frequentes").classes("text-base font-bold")
        if not erros:
            ui.label("Nenhum erro.").classes("text-gray-500")
        for (categoria, mensagem), quantidade in erros.most_common(15):
            with ui.row().classes("w-full items-start no-wrap"):
                ui.badge(str(quantidade)).classes("mt-1")
                ui.label(categoria).classes("w-40 text-sm font-medium")
                ui.label(mensagem).classes("text-sm flex-1")


@ui.page("/tarefas")
def tarefas() -> None:
    cabecalho("Tarefas")
    retrato, lista, linhas = carregar_linhas()
    barra_dados(retrato, lista)
    todas = sorted((_linha_tabela(l) for l in linhas), key=lambda l: (l["limite"] or "9999", l["ccs"]))
    filtros = {"sistema": "SIMBA", "situacao": "Todas", "origem": "Todas", "prazo": "Todos", "so_erros": False}

    def filtradas() -> list[dict]:
        return [
            l
            for l in todas
            if (filtros["sistema"] == "Todos" or l["sistema"] == filtros["sistema"])
            and (filtros["situacao"] == "Todas" or l["situacao"] == filtros["situacao"])
            and (filtros["origem"] == "Todas" or (l["na_lista"] == "Sim") == (filtros["origem"] == "Na lista"))
            and (filtros["prazo"] == "Todos" or l["prazo"] == filtros["prazo"])
            and (not filtros["so_erros"] or l["categoria_erro"])
        ]

    def atualizar() -> None:
        grade.options["rowData"] = filtradas()
        grade.update()
        contador.text = f"{len(grade.options['rowData']):,} linha(s)".replace(",", ".")

    def filtrar(chave: str, valor: object) -> None:
        filtros[chave] = valor
        atualizar()

    with ui.row().classes("w-full items-center gap-4"):
        ui.select({"SIMBA": "Simba (RPA)", "STA": "STA", "Todos": "Todos"}, value="SIMBA", label="Envio",
                  on_change=lambda e: filtrar("sistema", e.value)).classes("w-32")
        situacoes = ["Todas"] + sorted({l["situacao"] for l in todas})
        ui.select(situacoes, value="Todas", label="Situação",
                  on_change=lambda e: filtrar("situacao", e.value)).classes("w-44")
        ui.select(["Todas", "Na lista", "Fora da lista"], value="Todas", label="Origem",
                  on_change=lambda e: filtrar("origem", e.value)).classes("w-36")
        ui.select(["Todos", "No prazo", "Vencido"], value="Todos", label="Prazo",
                  on_change=lambda e: filtrar("prazo", e.value)).classes("w-32")
        ui.switch("Só com erro", on_change=lambda e: filtrar("so_erros", e.value))
        busca = ui.input("Buscar (CCS, atendimento, JUDTASK, erro...)").classes("w-80")
        contador = ui.label()
        ui.space()
        simular = ui.switch("Simulação (não grava nem envia)", value=True)
        ui.button("Executar selecionados", icon="play_arrow", color="green", on_click=lambda: play())

    grade = ui.aggrid(
        {
            "columnDefs": [
                {"field": campo, "headerName": titulo, "width": largura, "filter": True, "sortable": True,
                 **({"tooltipField": "erro"} if campo == "erro" else {})}
                for campo, titulo, largura in COLUNAS
            ],
            "rowData": [],
            "rowSelection": {
                "mode": "multiRow",
                "checkboxes": True,
                "headerCheckbox": True,
                "selectAll": "filtered",
                ":isRowSelectable": "(node) => node.data && node.data.selecionavel",
            },
            "pagination": True,
            "paginationPageSize": 100,
            "tooltipShowDelay": 300,
        },
        auto_size_columns=False,
    ).classes("w-full").style("height: 62vh")
    busca.on_value_change(lambda e: grade.run_grid_method("setGridOption", "quickFilterText", e.value))
    atualizar()

    async def play() -> None:
        selecionadas = await grade.get_selected_rows()
        if not selecionadas:
            ui.notify("Selecione os casos (só com work item Pendente ou Falha, sem comprovante)", type="warning")
            return
        bloqueios, avisos = checar_lote(selecionadas, simular.value)
        with ui.dialog() as dialogo, ui.card().classes("min-w-[40rem]"):
            modo = "SIMULAÇÃO: nada é gravado no ServiceNow nem enviado" if simular.value else (
                "EXECUÇÃO REAL: valida, TRANSMITE AO ÓRGÃO e grava no ServiceNow"
            )
            ui.label(f"{len(selecionadas)} caso(s) selecionado(s)").classes("text-lg font-bold")
            ui.label(modo).classes("text-purple-700" if simular.value else "text-red-700 font-bold")
            for texto in bloqueios:
                ui.label(f"⛔ {texto}").classes("text-red-700")
            for texto in avisos:
                ui.label(f"⚠ {texto}").classes("text-orange-700")
            if not bloqueios:
                ui.label("Durante a execução não use a VM: o Simba depende do foco das janelas.").classes(
                    "text-sm text-gray-600"
                )
            with ui.row():
                ui.button("Cancelar", on_click=dialogo.close).props("flat")
                if not bloqueios:
                    ui.button("Iniciar", color="green", on_click=lambda: iniciar(dialogo, selecionadas))
        dialogo.open()

    def iniciar(dialogo, selecionadas: list[dict]) -> None:
        lista_lote = disparar(selecionadas, simular.value)
        dialogo.close()
        ui.notify(f"Lote iniciado ({len(selecionadas)} casos). Log: {lista_lote.with_suffix('.log')}", type="positive")
        ui.navigate.to("/")


@ui.page("/configuracao")
def configuracao() -> None:
    cabecalho("Configuração")
    ui.label("Valores lidos do .env da VM. Para alterar, edite o .env (ou o CSV de chaves) e reinicie o console; "
             "o runner relê o CSV de chaves a cada envio.").classes("text-sm text-gray-600")

    def existe(caminho: Path) -> str:
        return "OK" if caminho.exists() else "NÃO ENCONTRADO"

    ambiente = [
        ("ServiceNow", config.SN_INSTANCIA, "OK" if config.SN_INSTANCIA else "VAZIO"),
        ("Usuário de integração", config.SN_USUARIO, "senha preenchida" if config.SN_SENHA else "SENHA VAZIA"),
        ("Limite de requisições/min", f"{config.SN_REQUISICOES_POR_MINUTO:.0f}", "bloqueio acima de 100 no total"),
        ("Work items criados desde", config.ITENS_DESDE or "todas as datas", ""),
        ("Transmite após validar", "sim" if config.TRANSMITIR_APOS_VALIDAR else "não", ""),
        ("Simba Validador", str(config.SIMBA_EXE), existe(config.SIMBA_EXE)),
        ("Simba Transmissor", str(config.TRANSMISSOR_EXE), existe(config.TRANSMISSOR_EXE)),
        ("dadosValidador (Validador)", str(config.SIMBA_VALIDADOR_DADOS), existe(config.SIMBA_VALIDADOR_DADOS)),
        ("dadosValidador (Transmissor)", str(config.SIMBA_TRANSMISSOR_DADOS), existe(config.SIMBA_TRANSMISSOR_DADOS)),
        ("Transmitidos (comprovantes)", str(config.TRANSMITIDOS), existe(config.TRANSMITIDOS)),
        ("Arquivo (casos processados)", str(config.ARQUIVO_DIR), existe(config.ARQUIVO_DIR)),
        ("Trabalho (downloads)", str(config.TRABALHO_DIR), existe(config.TRABALHO_DIR)),
        ("Logs", str(config.LOGS_DIR), existe(config.LOGS_DIR)),
        ("Java Access Bridge", config.JAB_DLL, existe(Path(config.JAB_DLL))),
        ("Console", f"{config.CONSOLE_HOST}:{os.environ.get('CONSOLE_PORTA') or 8080}", str(config.CONSOLE_DIR)),
    ]
    with ui.card().classes("w-full"):
        ui.label("Ambiente").classes("text-base font-bold")
        tabela(["Item", "Valor", "Situação"], ambiente)

    with ui.card().classes("w-full"):
        ui.label("Chaves do Transmissor").classes("text-base font-bold")
        tabela(["Item", "Valor", "Situação"], [
            ("Pasta dos arquivos .ASB", str(config.CHAVES_DIR), existe(config.CHAVES_DIR)),
            ("CSV de chaves (NOME DA CHAVE;SENHA;RESPONSÁVEL)", str(config.CHAVES_CSV), existe(config.CHAVES_CSV)),
        ])
        try:
            grupos = chaves.por_orgao(chaves.ler())
        except chaves.ChaveIndisponivel as erro:
            ui.label(str(erro)).classes("text-red-700")
            grupos = {}
        linhas_chaves = []
        for orgao, candidatas in sorted(grupos.items()):
            chave = chaves.escolher(candidatas)
            outras = ", ".join(c.arquivo for c in candidatas if c is not chave)
            linhas_chaves.append({
                "orgao": orgao,
                "arquivo": chave.arquivo,
                "existe": "Sim" if chave.existe else "Não",
                # A senha nunca sai da VM: o navegador só sabe se ela está preenchida.
                "senha": "•••••••• (preenchida)" if chave.senha else "VAZIA",
                "responsavel": chave.responsavel,
                "situacao": chaves.situacao(chave),
                "outras": outras,
            })
        prontas = sum(l["situacao"] == "OK" for l in linhas_chaves)
        ui.label(f"{len(linhas_chaves)} órgão(s) no CSV · {prontas} pronto(s) para enviar").classes("text-sm")
        ui.aggrid({
            "columnDefs": [
                {"field": "orgao", "headerName": "Órgão", "width": 90, "sort": "asc"},
                {"field": "arquivo", "headerName": "Arquivo da chave", "width": 230},
                {"field": "existe", "headerName": "Arquivo na pasta", "width": 140},
                {"field": "senha", "headerName": "Senha", "width": 190},
                {"field": "responsavel", "headerName": "Responsável", "width": 160},
                {"field": "situacao", "headerName": "Situação", "width": 260, "filter": True},
                {"field": "outras", "headerName": "Outras linhas do CSV para o órgão", "width": 260},
            ],
            "rowData": linhas_chaves,
        }, auto_size_columns=False).classes("w-full").style("height: 45vh")

    with ui.card().classes("w-full"):
        ui.label("Lista do Bacen (fonte da verdade)").classes("text-base font-bold")
        try:
            lista = lista_bacen.carregar()
        except ValueError as erro:
            ui.label(str(erro)).classes("text-red-700")
            lista = None
        requisicoes = lista["requisicoes"] if lista else []
        tabela(["Item", "Valor", "Situação"], [
            ("Planilha", str(config.LISTA_BACEN), existe(config.LISTA_BACEN)),
            ("Requisições do CCS", f"{len(requisicoes):,}".replace(",", "."), ""),
            ("Enviadas pelo Simba (escopo do RPA)",
             f"{sum(r['sistema'] == lista_bacen.SIMBA for r in requisicoes):,}".replace(",", "."), ""),
            ("Enviadas pelo STA (fora do RPA)",
             f"{sum(r['sistema'] != lista_bacen.SIMBA for r in requisicoes):,}".replace(",", "."), ""),
            ("Vencidas (prazo de resposta já passou)",
             f"{sum(lista_bacen.prazo(r['limite']) == 'Vencido' for r in requisicoes):,}".replace(",", "."), ""),
            ("Lida em", lista["lida_em"].replace("T", " ") if lista else "", ""),
        ])


def tabela(colunas: list[str], linhas: list[tuple]) -> None:
    ui.table(
        columns=[{"name": str(i), "label": c, "field": str(i), "align": "left"} for i, c in enumerate(colunas)],
        rows=[{str(i): v for i, v in enumerate(l)} for l in linhas],
    ).props("dense flat wrap-cells").classes("w-full")


def _linha_tabela(linha: consulta.Linha) -> dict:
    dados = {campo: getattr(linha, campo) for campo, _, _ in COLUNAS}
    dados = {k: ("Sim" if v else "Não") if isinstance(v, bool) else v for k, v in dados.items()}
    dados["work_item"] = linha.work_item
    dados["selecionavel"] = bool(linha.work_item) and linha.situacao in SELECIONAVEIS and not linha.transmitido
    return dados


def main() -> None:
    config.CONSOLE_DIR.mkdir(parents=True, exist_ok=True)
    ui.run(title="Console Simba RPA", host=config.CONSOLE_HOST, port=int(os.environ.get("CONSOLE_PORTA") or 8080),
           reload=False, show=True, favicon="📋")

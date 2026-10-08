"""Fluxo completo de um atendimento no Simba: cadastro e gravação, validação dos arquivos, geração do pacote
de envio (Validador) e transmissão ao órgão (Transmissor)."""
import logging
from pathlib import Path
from typing import Callable, Optional

from simba import arquivo, cadastro, config, correcao, geracao, transmissao, validacao
from simba.app import SimbaApp
from simba.cadastro import Caso
from simba.geracao import ResultadoGeracao
from simba.transmissao import ResultadoTransmissao

log = logging.getLogger(__name__)


def processar(app: SimbaApp, caso: Caso, pasta_arquivos: Path) -> ResultadoGeracao:
    """Cada etapa reinicia o Simba e repete em falha técnica; erros de negócio (SimbaAviso) sobem na hora.

    GABs reprovados só por erros conhecidos (codificação, BOM, tamanho de linha) são corrigidos em
    `pasta_arquivos` e validados de novo uma vez (simba.correcao); as correções vêm em `correcoes`.
    """
    # Fora da etapa: se o Simba cair depois da correção, a nova tentativa já valida os arquivos corrigidos.
    correcoes: list[str] = []

    def cadastrar(a: SimbaApp) -> None:
        cadastro.preencher_caso(a, caso)
        cadastro.gravar(a)

    def reprovado_apos_correcao(reprovado: validacao.ArquivosReprovados) -> validacao.ArquivosReprovados:
        aplicadas = "\n".join(f"- {c}" for c in correcoes)
        return validacao.ArquivosReprovados(
            f"{reprovado.message}\nCorreções automáticas aplicadas antes desta validação:\n{aplicadas}"
        )

    def validar(a: SimbaApp) -> None:
        try:
            validacao.validar_arquivos(a, caso.pasta, caso.tipo, pasta_arquivos)
            return
        except validacao.ArquivosReprovados as reprovado:
            if correcoes:
                # Arquivos já corrigidos numa tentativa anterior da etapa e ainda reprovados.
                raise reprovado_apos_correcao(reprovado) from reprovado
            # Só os GABs (Corretora) têm leiaute posicional conhecido.
            novas = correcao.corrigir(pasta_arquivos, reprovado.message) if caso.tipo == "Corretora" else []
            if not novas:
                raise
            correcoes.extend(novas)
            log.info("%s: correções automáticas: %s", caso.pasta, "; ".join(novas))
        try:
            validacao.validar_arquivos(a, caso.pasta, caso.tipo, pasta_arquivos)
        except validacao.ArquivosReprovados as reprovado:
            raise reprovado_apos_correcao(reprovado) from reprovado

    def validar_e_gerar(a: SimbaApp) -> ResultadoGeracao:
        # Validação e geração ficam na mesma etapa: o Passo 3 só abre a partir de um Passo 2 aprovado.
        validar(a)
        geracao.abrir_passo3(a, caso.pasta)
        resultado = geracao.gerar(a, caso.pasta)
        geracao.voltar_ao_inicio(a)
        resultado.correcoes = list(correcoes)
        return resultado

    if arquivo.dados_validador(caso.pasta).exists() and app.is_alive():
        # Reprocessar um caso que o Validador aberto já carregou falha ao gravar ("Exclua o atendimento e crie-o
        # novamente"); reaberto, o Validador regrava o caso existente normalmente.
        log.info("%s já está no dadosValidador; reabrindo o Validador antes do cadastro", caso.pasta)
        app.kill()
    app.run_step("cadastro", cadastrar)
    return app.run_step("validar_e_gerar", validar_e_gerar)


def transmitir(
    app: SimbaApp,
    atendimento: str,
    pasta_arquivos: Optional[Path],
    chave: Path,
    senha: str,
    antes_de_enviar: Callable[[], None] = lambda: None,
) -> ResultadoTransmissao:
    """Envia o pacote gerado por `processar`; `app` é um SimbaApp(TRANSMISSOR).

    Uma pasta por caso, Transmitidos/<atendimento>/, com o comprovante (PDF do Transmissor) e o
    <atendimento>_GABs.zip (arquivos validados de `pasta_arquivos`, se houver) lado a lado.
    Falha antes do Enviar reinicia o Transmissor e repete; depois do Enviar não há nova tentativa
    (TransmissaoIncerta). `antes_de_enviar` roda logo antes do clique (ex.: registrar a etapa na fila).
    """
    destino = config.TRANSMITIDOS / atendimento

    def enviar(a: SimbaApp) -> ResultadoTransmissao:
        transmissao.selecionar_atendimento(a, atendimento)
        transmissao.carregar_chave(a, chave, senha)
        antes_de_enviar()
        return transmissao.enviar(a, destino)

    resultado = app.run_step("transmitir", enviar)
    if pasta_arquivos is not None:
        transmissao.arquivar_arquivos(atendimento, pasta_arquivos, destino)
    return resultado

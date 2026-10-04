"""Fluxo completo de um atendimento no Simba: cadastro e gravação, validação dos arquivos e geração do pacote de envio."""
from pathlib import Path

from simba import cadastro, geracao, validacao
from simba.app import SimbaApp
from simba.cadastro import Caso
from simba.geracao import ResultadoGeracao


def processar(app: SimbaApp, caso: Caso, pasta_arquivos: Path) -> ResultadoGeracao:
    """Cada etapa reinicia o Simba e repete em falha técnica; erros de negócio (SimbaAviso) sobem na hora."""

    def cadastrar(a: SimbaApp) -> None:
        cadastro.preencher_caso(a, caso)
        cadastro.gravar(a)

    def validar_e_gerar(a: SimbaApp) -> ResultadoGeracao:
        # Validação e geração ficam na mesma etapa: o Passo 3 só abre a partir de um Passo 2 aprovado.
        validacao.validar_arquivos(a, caso.pasta, caso.tipo, pasta_arquivos)
        geracao.abrir_passo3(a, caso.pasta)
        resultado = geracao.gerar(a, caso.pasta)
        geracao.fechar(a)
        return resultado

    app.run_step("cadastro", cadastrar)
    return app.run_step("validar_e_gerar", validar_e_gerar)

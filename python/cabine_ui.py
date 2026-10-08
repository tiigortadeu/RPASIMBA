"""Driver orientado a controles para a Cabine CCS-JUD.

O menu lateral da Cabine é um painel customizado e atualmente exige um
fallback posicional isolado. Depois que Controle de Mensagens é aberto, as
ações expostas pela janela são executadas por UI Automation, sem mover o
cursor.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from pywinauto import Desktop
from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.keyboard import send_keys


class CabineUIError(RuntimeError):
    """Estado inesperado ou controle ausente na Cabine."""


@dataclass(frozen=True)
class ResultadoPesquisa:
    simba_code: str
    quantidade: int | None


class CabineUIDriver:
    """Executa ações determinísticas nos controles acessíveis da Cabine."""

    TITULO_JANELA = "Cabine CCS-JUD"
    TITULO_ABA_REQUISICAO = r"^Requisi.*Movimenta.*Financeira.*"
    def __init__(self, hwnd: int, timeout: float = 30.0, poll_interval: float = 0.1) -> None:
        self.hwnd = hwnd
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._janela: UIAWrapper | None = None
        self._resposta: Any | None = None
        self._aba_requisicao: UIAWrapper | None = None
        self._campo_pesquisa: UIAWrapper | None = None
        self._botao_pesquisar: UIAWrapper | None = None
        self._grade: UIAWrapper | None = None
        self._campo_pesquisa_nativo: Any | None = None
        self._botao_pesquisar_nativo: Any | None = None
        self._grade_nativa: Any | None = None

    @property
    def janela(self) -> UIAWrapper:
        if self._janela is None:
            self._janela = Desktop(backend="uia").window(handle=self.hwnd)
        return self._janela

    def validar_janela(self) -> UIAWrapper:
        try:
            self.janela.wait("visible enabled ready", timeout=self.timeout)
        except Exception as exc:
            raise CabineUIError(
                f"Janela da Cabine não ficou pronta: hwnd={self.hwnd}"
            ) from exc
        if self.janela.window_text() != self.TITULO_JANELA:
            raise CabineUIError(
                f"Janela inesperada: {self.janela.window_text()!r}; "
                f"esperada {self.TITULO_JANELA!r}"
            )
        return self.janela

    def tem_resposta_aberta(self) -> bool:
        try:
            return any(
                janela.is_visible() and janela.is_enabled()
                for janela in Desktop(backend="win32").windows(
                    title_re=r"^Resposta de Requisi.*Movimenta.*Financeira.*"
                )
            )
        except Exception:
            return False

    def selecionar_requisicao(self) -> None:
        janela = self.validar_janela()
        try:
            aba = janela.child_window(
                title_re=self.TITULO_ABA_REQUISICAO,
                control_type="TabItem",
            )
            if not aba.is_visible() or not aba.is_enabled():
                aba.wait("visible enabled", timeout=self.timeout)
            self._aba_requisicao = aba
            aba.click_input()
        except Exception as exc:
            raise CabineUIError(
                "A aba 'Requisição de Movimentação Financeira' não foi encontrada "
                "ou não pôde ser selecionada"
            ) from exc

        self._esperar_controle(
            lambda: self._controles_pesquisa_nativos(),
            "campo 'Nº Ctrl Envio'",
        )

    def pesquisar(self, simba_code: str) -> ResultadoPesquisa:
        codigo = simba_code.strip()
        if not codigo:
            raise ValueError("simba_code não pode ficar vazio")

        campo, botao = self._controles_pesquisa_nativos()
        try:
            campo.set_edit_text(codigo)
            if not botao.is_visible() or not botao.is_enabled():
                raise CabineUIError("Botão 'Pesquisar' ficou indisponível")
            botao.click_input()
        except Exception as exc:
            raise CabineUIError(
                f"Não foi possível pesquisar o simba_code={codigo}"
            ) from exc

        self._esperar_pesquisa_estabilizar()
        return ResultadoPesquisa(simba_code=codigo, quantidade=None)

    def identificar_grade(self) -> Any:
        """Retorna a grade nativa para uma estratégia de leitura especializada.

        O TdxDBGrid não expõe células na árvore UIA/MSAA observada. O método
        falha explicitamente se a grade não estiver presente, sem selecionar
        qualquer linha.
        """
        if self._grade is not None:
            if self._grade_nativa is not None:
                try:
                    if self._grade_nativa.is_visible() and self._grade_nativa.is_enabled():
                        return self._grade_nativa
                except Exception:
                    self._grade_nativa = None
            try:
                self._grade_nativa = self._localizar_grade_nativa()
                return self._grade_nativa
            except Exception:
                pass
            try:
                self._grade.wait("visible enabled", timeout=1)
                return self._grade
            except Exception:
                self._grade = None
        try:
            grade = self.janela.child_window(class_name="TdxDBGrid")
            grade.wait("visible enabled", timeout=self.timeout)
            self._grade = grade
            return grade
        except Exception as exc:
            raise CabineUIError(
                "A grade TdxDBGrid não foi encontrada após a pesquisa"
            ) from exc

    def selecionar_linha_por_identificadores(
        self,
        simba_code: str,
        official_letter_number: str,
    ) -> None:
        if not simba_code.strip() or not official_letter_number.strip():
            raise ValueError(
                "simba_code e official_letter_number não podem ficar vazios"
            )
        raise CabineUIError(
            "A grade TdxDBGrid não expõe suas células via UI Automation; "
            "a seleção por simba_code + official_letter_number está bloqueada "
            "até existir um leitor estruturado validado"
        )

    def selecionar_linha_por_indice_teste(self, indice: int) -> None:
        """Seleciona uma linha por teclado somente para teste controlado."""
        if indice < 0:
            raise ValueError("indice não pode ser negativo")
        try:
            grade = self.identificar_grade()
            grade.set_focus()
            send_keys("{HOME}")
            for _ in range(indice):
                send_keys("{DOWN}")
        except Exception as exc:
            raise CabineUIError(
                f"Não foi possível selecionar a linha de teste índice={indice}"
            ) from exc

    def clicar_responder(self) -> None:
        """Invoca o segundo botão de ação, identificado pela posição no painel."""
        try:
            botoes: list[tuple[int, UIAWrapper]] = []
            for botao in self.janela.descendants(control_type="Button"):
                retangulo = botao.rectangle()
                if (
                    retangulo.top >= 900
                    and botao.is_visible()
                    and botao.is_enabled()
                ):
                    botoes.append((retangulo.left, botao))
            botoes.sort(key=lambda item: item[0])
            if len(botoes) < 2:
                raise CabineUIError("Botão Responder não foi identificado")
            botoes[1][1].invoke()
            self.selecionar_atendimento_requisicao()
        except CabineUIError:
            raise
        except Exception as exc:
            raise CabineUIError("Não foi possível clicar em Responder") from exc

    def selecionar_atendimento_requisicao(self) -> None:
        """Seleciona a primeira opção do atendimento, cujo código começa por ``01``."""
        try:
            resposta = self._localizar_resposta()
            combos = [
                combo
                for combo in resposta.descendants(class_name="TJDComboBox")
                if combo.is_visible() and combo.is_enabled()
            ]
            if not combos:
                raise CabineUIError(
                    "Campo 'Atendimento da REQUISIÇÃO' não foi identificado"
                )

            combo = min(combos, key=lambda item: item.rectangle().top)
            combo.click_input()
            send_keys("01")
            send_keys("{ENTER}")

            texto = combo.window_text().strip()
            if not texto:
                edicoes = [
                    campo
                    for campo in combo.descendants(class_name="Edit")
                    if campo.is_visible()
                ]
                texto = next(
                    (campo.window_text().strip() for campo in edicoes if campo.window_text().strip()),
                    "",
                )
            if texto and not texto.startswith("01"):
                raise CabineUIError(
                    f"Atendimento selecionado inesperado: {texto!r}; esperado prefixo '01'"
                )
        except CabineUIError:
            raise
        except Exception as exc:
            raise CabineUIError(
                "Não foi possível selecionar a primeira opção de "
                "Atendimento da REQUISIÇÃO"
            ) from exc

    def selecionar_arquivo(self, caminho: str, finalidade: str) -> None:
        """Abre o seletor nativo e preenche um arquivo sem confirmar a resposta."""
        from pathlib import Path

        arquivo = Path(caminho)
        if not arquivo.is_file():
            raise FileNotFoundError(f"Arquivo {finalidade} não encontrado: {arquivo}")

        try:
            resposta = self._localizar_resposta()
            self._clicar_seletor_de_arquivo(resposta, finalidade)
            dialogo = self._localizar_dialogo_de_arquivo()
            self._preencher_dialogo_de_arquivo(dialogo, arquivo)
        except Exception as exc:
            raise CabineUIError(
                f"Não foi possível selecionar o arquivo {finalidade}: {arquivo}"
            ) from exc

        self._tratar_erro_de_arquivo(finalidade)

    def _preencher_campo_de_arquivo(
        self, resposta: Any, finalidade: str, arquivo: Any
    ) -> None:
        campos = [
            campo
            for campo in resposta.descendants(class_name="TEdit")
            if campo.is_visible()
            and campo.is_enabled()
            and 400 <= campo.rectangle().top <= 700
            and campo.rectangle().width() >= 400
        ]
        campos.sort(key=lambda campo: (campo.rectangle().top, campo.rectangle().left))
        indice = 0 if finalidade == "ACCS100" else 1
        if len(campos) <= indice:
            raise CabineUIError(
                f"Campo do arquivo {finalidade} não foi identificado na janela de resposta"
            )

        campo = campos[indice]
        campo.click_input()
        campo.set_edit_text(str(arquivo))
        campo.type_keys("{TAB}")
        if campo.window_text().strip() != str(arquivo):
            raise CabineUIError(
                f"Campo do arquivo {finalidade} não reteve o caminho selecionado"
            )

    def _localizar_resposta(self) -> Any:
        if self._resposta is not None:
            try:
                if self._resposta.is_visible() and self._resposta.is_enabled():
                    return self._resposta
            except Exception:
                self._resposta = None

        limite = time.monotonic() + self.timeout
        while time.monotonic() < limite:
            candidatos = Desktop(backend="win32").windows(
                title_re=r"^Resposta de Requisi.*Movimenta.*Financeira.*"
            )
            visiveis = [
                janela
                for janela in candidatos
                if janela.is_visible() and janela.is_enabled()
            ]
            if visiveis:
                self._resposta = visiveis[0]
                return self._resposta
            time.sleep(self.poll_interval)
        raise CabineUIError(
            "A janela 'Resposta de Requisição de Movimentação Financeira' "
            "não ficou disponível"
        )

    def _clicar_seletor_de_arquivo(self, resposta: Any, finalidade: str) -> None:
        campos = [
            campo
            for campo in resposta.descendants(class_name="TEdit")
            if campo.is_visible()
            and campo.is_enabled()
            and 400 <= campo.rectangle().top <= 700
            and campo.rectangle().width() >= 400
        ]
        campos.sort(key=lambda campo: (campo.rectangle().top, campo.rectangle().left))
        indice = 0 if finalidade == "ACCS100" else 1
        if len(campos) <= indice:
            raise CabineUIError(
                f"Campo do arquivo {finalidade} não foi identificado na janela de resposta"
            )

        campo = campos[indice]
        primeiro_campo = campos[0]
        x_icone = primeiro_campo.rectangle().right - resposta.rectangle().left + 12
        y_icone = (
            campo.rectangle().top
            - resposta.rectangle().top
            - 1
        )
        resposta.click_input(coords=(x_icone, y_icone))

    def _localizar_dialogo_de_arquivo(self) -> Any:
        limite = time.monotonic() + self.timeout
        while time.monotonic() < limite:
            uia = Desktop(backend="uia").windows(
                title_re=r"^(Selecione o comprovante|Abrir).*"
            )
            candidatos = [
                janela
                for janela in uia
                if janela.is_visible() and janela.is_enabled()
            ]
            if candidatos:
                return candidatos[0]

            win32 = Desktop(backend="win32").windows(
                title_re=r".*(Selecione|Abrir|Explorador de Arquivos).*"
            )
            candidatos = [
                janela
                for janela in win32
                if janela.is_visible() and janela.is_enabled()
            ]
            if candidatos:
                return candidatos[0]
            time.sleep(self.poll_interval)
        raise CabineUIError("O diálogo nativo de seleção de arquivo não apareceu")

    def _preencher_dialogo_de_arquivo(self, dialogo: Any, arquivo: Any) -> None:
        edicoes = [
            campo
            for campo in dialogo.descendants(control_type="Edit")
            if campo.is_visible() and campo.is_enabled()
        ]
        if not edicoes:
            edicoes = [
                campo
                for campo in dialogo.descendants(class_name="Edit")
                if campo.is_visible() and campo.is_enabled()
            ]
        if not edicoes:
            if getattr(dialogo, "class_name", lambda: "")() not in {
                "CabinetWClass",
                "#32770",
            }:
                raise CabineUIError(
                    f"O diálogo de arquivo não expôs um campo para {arquivo}"
                )
            dialogo.set_focus()
            send_keys("^l")
            send_keys(str(arquivo.parent), with_spaces=True)
            send_keys("{ENTER}")
            send_keys(arquivo.name, with_spaces=True)
            send_keys("{ENTER}")
            return

        def automation_id(item: Any) -> str:
            valor = getattr(item, "automation_id", "")
            return str(valor() if callable(valor) else valor)

        campo = next((item for item in edicoes if automation_id(item) == "1148"), edicoes[-1])
        campo.set_edit_text(str(arquivo))
        botoes = [
            botao
            for botao in dialogo.descendants(control_type="Button")
            if botao.is_visible() and botao.is_enabled()
            and botao.window_text() in {"Abrir", "Open"}
        ]
        if botoes:
            botoes[0].click_input()
            return
        send_keys("{ENTER}")

    def _tratar_erro_de_arquivo(self, finalidade: str) -> None:
        alertas = [
            janela
            for janela in Desktop(backend="uia").windows()
            if janela.is_visible() and "Aten" in janela.window_text()
        ]
        if not alertas:
            return
        alerta = alertas[0]
        mensagem = alerta.window_text()
        try:
            alerta.child_window(title="OK", control_type="Button").invoke()
        except Exception:
            pass
        raise CabineUIError(
            f"A Cabine rejeitou o arquivo {finalidade}: {mensagem or 'erro de validação'}"
        )

    def _controle_pesquisa(self) -> UIAWrapper:
        if self._campo_pesquisa is not None and self._botao_pesquisar is not None:
            try:
                self._campo_pesquisa.wait("visible enabled", timeout=1)
                self._botao_pesquisar.wait("visible enabled", timeout=1)
                return self._campo_pesquisa
            except Exception:
                self._campo_pesquisa = None
                self._botao_pesquisar = None

        botoes = [
            botao
            for botao in self.janela.descendants(
                title="Pesquisar",
                control_type="Button",
            )
            if botao.is_visible() and botao.is_enabled()
        ]
        if not botoes:
            raise CabineUIError("Botão 'Pesquisar' não está disponível")

        botao = min(botoes, key=lambda item: item.rectangle().top)
        candidatos = [
            campo
            for campo in self.janela.descendants(control_type="Edit")
            if campo.is_visible() and campo.is_enabled()
        ]
        if not candidatos:
            raise CabineUIError("Nenhum campo de pesquisa editável está disponível")

        botao_rect = botao.rectangle()
        candidatos.sort(
            key=lambda campo: (
                abs(campo.rectangle().top - botao_rect.top),
                abs(campo.rectangle().right - botao_rect.left),
            )
        )
        self._botao_pesquisar = botao
        self._campo_pesquisa = candidatos[0]
        return self._campo_pesquisa

    def _controles_pesquisa_nativos(self) -> tuple[Any, Any]:
        if (
            self._campo_pesquisa_nativo is not None
            and self._botao_pesquisar_nativo is not None
            and self._campo_pesquisa_nativo.is_visible()
            and self._botao_pesquisar_nativo.is_visible()
            and self._campo_pesquisa_nativo.is_enabled()
            and self._botao_pesquisar_nativo.is_enabled()
        ):
            return self._campo_pesquisa_nativo, self._botao_pesquisar_nativo

        janela = Desktop(backend="win32").window(handle=self.hwnd)
        botoes = [
            botao
            for botao in janela.descendants(class_name="TButton")
            if botao.window_text() == "Pesquisar"
            and botao.is_visible()
            and botao.is_enabled()
        ]
        edicoes = [
            campo
            for campo in janela.descendants(class_name="TEdit")
            if campo.is_visible()
            and campo.is_enabled()
            and 150 <= campo.rectangle().top <= 300
        ]
        if not botoes or not edicoes:
            raise CabineUIError("Controles nativos da pesquisa ainda não estão disponíveis")

        self._botao_pesquisar_nativo = min(botoes, key=lambda item: item.rectangle().top)
        self._campo_pesquisa_nativo = min(edicoes, key=lambda item: item.rectangle().left)
        return self._campo_pesquisa_nativo, self._botao_pesquisar_nativo

    def _localizar_grade_nativa(self) -> Any:
        janela = Desktop(backend="win32").window(handle=self.hwnd)
        grades = [
            grade
            for grade in janela.descendants(class_name="TdxDBGrid")
            if grade.is_visible() and grade.is_enabled()
        ]
        if not grades:
            raise CabineUIError("A grade TdxDBGrid ainda não está disponível")
        return max(grades, key=lambda item: item.rectangle().width() * item.rectangle().height())

    def _esperar_controle(self, resolver: Any, descricao: str) -> Any:
        limite = time.monotonic() + self.timeout
        ultimo_erro: Exception | None = None
        while time.monotonic() < limite:
            try:
                return resolver()
            except Exception as exc:
                ultimo_erro = exc
                time.sleep(self.poll_interval)
        raise CabineUIError(f"Controle {descricao} não ficou disponível") from ultimo_erro

    def _esperar_pesquisa_estabilizar(self) -> None:
        try:
            self.identificar_grade()
        except CabineUIError:
            raise

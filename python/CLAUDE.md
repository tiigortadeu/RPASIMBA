# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é

RPA em Python (Windows) que processa atendimentos judiciais do SIMBA: consome work items das filas do RPA Hub no ServiceNow, cadastra/valida/gera o pacote no **Simba Validador** e transmite pelo **Simba Transmissor** (apps Java desktop, automatizados via Java Access Bridge). Os scripts `cabine_*` cuidam da etapa seguinte na **Cabine CCS-JUD** (app nativo, pywinauto/UIA). Código, comentários e mensagens são em português.

## Ambiente

- Windows, Python 3.12, `.venv` na raiz: `py -3.12 -m venv .venv` e `.venv\Scripts\pip install -r requirements.txt`.
- `xpi-automia` (SDK do Automia, usado só por `bot.py`) vem do índice interno; fora da rede interna, instale o resto.
- Toda configuração de máquina (caminhos, credenciais, chaves) vem do `.env` na raiz, carregado em `simba/config.py`. Nunca hardcode caminhos: adicione a variável em `config.py` (com `_caminho`, que trata valor vazio como não definido) e documente em `.env.example`.
- O `.env` contém segredos (SN_SENHA, SIMBA_SENHA_*): não ler nem imprimir.
- **Limite do ServiceNow**: o usuário de integração é bloqueado acima de 100 requisições/minuto. Todo request passa por `servicenow._cadenciar` (`SN_REQUISICOES_POR_MINUTO`, por processo; com várias VMs no mesmo usuário a soma precisa ficar abaixo de 100). Esse limite, e não o Simba, é o gargalo: qualquer mudança no runner deve contar requisições por item (`tests/test_esteira.py` mede).
- Simba: um item por vez por sessão Windows. Validador e Transmissor juntos na mesma sessão disputam foco; para paralelizar, mais VMs.

## Testes

```
.venv\Scripts\pytest                         # padrão: exclui markers cadastro e servicenow
.venv\Scripts\pytest tests\test_arquivo.py::test_arquiva_as_duas_copias
.venv\Scripts\pytest -m cadastro             # cria atendimentos locais no Simba (casos fictícios 002-PF-*)
.venv\Scripts\pytest -m cadastro tests\test_esteira.py -s   # esteira com Simba real + ServiceNow em memória (tests/sn_falso.py)
.venv\Scripts\pytest -m servicenow           # cria/exclui work items na fila SN_FILA_TESTE
```

- `-m cadastro` e `-m servicenow` só com autorização do usuário (`pytest.ini`).
- Vários testes do conjunto padrão abrem o Simba Validador real (fixtures `simba`/`transmissor` em `tests/conftest.py`), então exigem o Simba instalado e uma sessão de desktop.
- Scripts de teste manuais na raiz (`testar_*.py`), todos sem `Enviar`/`Confirmar`:
  - `testar_servicenow.py`: conectividade SN (somente GET).
  - `testar_e2e_servicenow_sem_enviar.py --numero <JUDTASK> [--sem-chave]`: dados/GABs reais do SN, Validador real, Transmissor até a chave (ou só a seleção do atendimento com `--sem-chave`).
  - `testar_fila_servicenow_sem_enviar.py --fila-id <sys_id>`: até 5 itens pendentes de uma fila, sem reservar.
  - `testar_e2e_local.py`, `testar_fluxo_completo_local.py`, `cabine_rpa.py`: incluem a Cabine (só existe em outra máquina).

## Console

`.venv\Scripts\python -m console` (NiceGUI, http://localhost:8080; porta em `CONSOLE_PORTA`). Sem base de dados: o ServiceNow é a fonte de verdade.
- `simba/consulta.py`: "Baixar casos" lê, paginado, os work items da fila e as JUDTASKs (com `parent` = JUD) e grava um retrato JSON em `SIMBA_CONSOLE`; cruza com a lista do Bacen (`simba/lista_bacen.py`, `SIMBA_LISTA_BACEN`, aba com `NUM_CTRL_CCS`; cache JSON), uma linha por requisição do CCS, casada pelo `official_letter_number` da JUD; o escopo do RPA são as requisições com `CD_SISTEMA_ENVIO=Simba` (as de STA ficam fora) e exporta Excel. Só work items criados a partir de `SIMBA_ITENS_DESDE` (vale também para a reserva e o reaper). Validado = sucesso ou falha em etapa pós-validação (o runner grava `[etapa]` no início da mensagem do work item); Transmitido = `evidence_attachment`; Cabine = JUD `state=3` (Concluído).
- Play: `console/app.py` grava a lista de work items e dispara `python -m simba.runner --lista <json> [--simular]` destacado; o runner escreve `andamento.json` (`simba/andamento.py`) e para depois do caso atual se existir o arquivo `parar`.
- `--simular` (`simba/simulacao.py`): lê da instância real, grava só em memória e simula o Enviar; carrega a chave de verdade quando o órgão tem uma completa.
- Chaves (`simba/chaves.py`): arquivo .ASB e senha por órgão vêm do CSV `SIMBA_CHAVES_CSV`; a tela Configuração mostra a situação de cada órgão e nunca envia a senha ao navegador.
- O runner destacado não recebe foco de janela: nada no fluxo do Simba pode depender de `SetForegroundWindow` (a pasta do Passo 2 é preenchida por `set_text` do JAB).

## Regras de segurança

- O clique em **Enviar** do Transmissor envia ao órgão (produção). Nenhum teste ou script de teste pode chegar nele; `Confirmar` na Cabine idem.
- Depois do Enviar não há nova tentativa (`TransmissaoIncerta`); o anti-duplicidade é o campo `evidence_attachment` da JUDTASK.

## Arquitetura

Entrada: `bot.py` (Automia, parâmetros `filas` e `max_itens`) -> `simba.runner.executar_uma_vez(filas, max_itens)`. Com `max_itens > 1` (só fila do Validador) roda `Runner.processar_lote`: esteira em que uma thread do SN reserva/baixa o próximo caso e registra o anterior enquanto o Simba processa o atual. `python -m simba.runner --lote N` faz o mesmo pela linha de comando; sem `--lote` é o loop legado.

- `simba/fila.py`: work items (`sn_rpa_fdn_work_queue_item`), pensado para um runner por fila. Uma listagem serve para vários itens; a reserva lê e grava o token em `remarks`, sem releitura. Só a entrada numa etapa sem retorno (`enviando`) vai ao SN, depois de `confirmar` a posse; as outras etapas ficam no item local. Heartbeat mantém o lease; reaper devolve itens de runners mortos.
- `simba/runner.py`: handlers `validador`/`transmissor`; o do Validador é dividido em `_baixar_caso` (SN), `_processar_no_simba` (Simba) e `_registrar_resultado` (SN: comprovante primeiro, zip único `<atendimento>_saida_simba.zip`, conclusão). Mapeia exceções para o destino do item: `SimbaAviso`/`DadosInvalidos` = falha de negócio; `TransmissaoIncerta`/`AcaoManual` = manual; `StepFailed`/`ServiceNowError`/`OSError` = devolve à fila (conta tentativa). Toda parada é comentada na JUDTASK (`simba/notificacao.py`).
- `simba/fluxo.py`: `processar` (etapas `cadastro` e `validar_e_gerar`) e `transmitir`. Cada etapa roda em `SimbaApp.run_step`, que parte da tela inicial, reinicia o Simba e repete em erro técnico (`RECOVERABLE`), mas sobe na hora um `SimbaAviso` (diálogo de negócio do Simba).
- `simba/app.py` + `simba/jab.py` + `simba/screens.py`: `SimbaApp` controla processo (exe + JVM do .jar) e janelas; `screens.py` mapeia telas/controles por caminho JAB (vindo dos .iBot), com `label` como fallback de busca.
- `simba/cadastro.py`, `validacao.py`, `geracao.py`, `transmissao.py`: Passo 1 / Passo 2 / Passo 3 do Validador e a tela do Transmissor. `correcao.py` corrige defeitos conhecidos de GABs posicionais (codificação, BOM, tamanho de linha) e revalida uma vez.
- `simba/arquivo.py`: o Simba lê o `dadosValidador` um nível acima da pasta do .exe. Se Validador e Transmissor têm pastas diferentes, `sincronizar_transmissor` copia o atendimento antes de transmitir; `arquivar_atendimento` tira o caso das listas do Simba. Só funciona com os programas fechados (o Validador mantém o `.zip.hash` aberto): na esteira o Validador volta ao Passo 1 entre os casos (`geracao.voltar_ao_inicio`) e é reiniciado a cada `VALIDADOR_REINICIO` casos para arquivar os acumulados.
- `simba/servicenow.py`: cliente REST (Table + Attachment API, basic auth, retry só em GET/PATCH). Tabela de tarefas: `x_xpi_ofj_judicial_office_task`.
- O Transmissor só lê a lista de atendimentos ao abrir: fechar (`kill`) antes de selecionar um atendimento novo. `SimbaApp.kill` fecha por WM_CLOSE antes de matar: matar a JVM de um programa tira o outro do Java Access Bridge.

# Plano de Implantação — ServiceNow + Validador + Transmissor

**Data:** 03/10/2026
**Pré-leitura:** [estado-atual.md](estado-atual.md)

## Objetivo

Ter uma aplicação Python que, sem intervenção humana:

1. busca no **ServiceNow** as tarefas judiciais pendentes (`x_xpi_ofj_judicial_office_task`);
2. baixa os anexos (arquivos a validar) e monta os dados do caso;
3. cadastra, valida e gera o pacote no **Simba Validador** (já implementado em `fluxo.processar`);
4. transmite o pacote pelo **Simba Transmissor**;
5. devolve o resultado ao ServiceNow: anexa os artefatos, registra work notes e **encerra a tarefa**, ou a devolve com o motivo.

### Decisões já tomadas

| Tema | Decisão |
|---|---|
| Acesso ao ServiceNow | REST API direta (Table API + Attachment API), **sem MCP** |
| Autenticação | Usuário de integração com basic auth (OAuth client credentials quando o time do SN confirmar) |
| Origem dos casos | **Filas do RPA Hub já existentes** (`sn_rpa_fdn_work_queue_item`: "Simba Validador", "Simba Transmissor"). O fluxo do SN que cria os itens e encaminha Validador → Transmissor continua igual; os runners Python substituem os robôs Intellibot |
| Escala | N runners sem estado (1 por sessão Windows), reserva por status + token (ver `simba/fila.py`) |
| Onde construir | PC da empresa (Simba Validador e Transmissor instalados) |

> **Atualização (05/10/2026):** a arquitetura de execução foi revista para N runners consumindo as filas do RPA Hub; está descrita em [estado-atual.md](estado-atual.md), seção "Runners". O orquestrador único da Fase 3 abaixo foi substituído por `python -m simba.runner`.

### Visão geral

```
            ┌─────────────── orquestrador.py (1 tarefa por vez) ───────────────┐
ServiceNow ─┤ listar → reservar → baixar anexos → montar Caso                   │
 (REST)     │      → fluxo.processar (Validador)  → transmissao (Transmissor)   │
            │      → anexar artefatos → work notes → encerrar / devolver        │
            └───────────────────────────────────────────────────────────────────┘
```

---

## Fase 0 — Ambiente no PC da empresa

| # | Atividade | Critério de pronto |
|---|---|---|
| 0.1 | Instalar Python 3.x, criar `python/.venv`, `pip install -r requirements.txt` | `import JABWrapper` funciona |
| 0.2 | Habilitar o Java Access Bridge (`jabswitch -enable` no JRE do Simba) e confirmar a DLL `WindowsAccessBridge-64.dll` | `scripts/dump_tree.py "Passo 1"` mostra a árvore |
| 0.3 | Confirmar a pasta do Simba; se não for `Documentos\Programas SIMBA`, definir `SIMBA_HOME` | `config.SIMBA_EXE` existe |
| 0.4 | Rodar `pytest` (sem `cadastro`), depois `pytest -m cadastro` com caso fictício autorizado | Toda a suíte verde |
| 0.5 | Validar **CC 3454** (tipo `Banco`) com arquivos de exemplo; criar o teste correspondente em `test_validacao.py` | Aprovação e reprovação CC 3454 cobertas |
| 0.6 | Adicionar `pywin32` explícito em `requirements.txt` (hoje vem como dependência transitiva) | Instalação limpa reproduzível |

Riscos: versão diferente do Simba/JRE pode mudar caminhos JAB. Mitigação: `test_selectors.py` aponta na hora o controle quebrado, e o `Control.label` permite fallback por papel+nome.

---

## Fase 1 — Integração com o ServiceNow (REST + OAuth 2.0)

### 1.1 Levantamento com o time do ServiceNow (pré-requisito)

| Item | Pergunta a responder |
|---|---|
| OAuth | Registro no *Application Registry* (client_id/secret). Grant: **client credentials** (preferido, se habilitado na instância) ou **password grant** com usuário de integração |
| Usuário/roles | Usuário técnico com acesso mínimo: leitura/escrita em `x_xpi_ofj_judicial_office_task`, leitura/escrita em `sys_attachment`, escrita em `work_notes` |
| Filtro de pendentes | Quais `state`/`assignment_group`/tipo identificam uma tarefa pronta para validação? |
| Estados de saída | Valores de estado para: **em processamento**, **encerrada com sucesso**, **devolvida por erro de negócio**; campos obrigatórios para encerrar (close code, close notes) |
| Mapeamento de campos | De qual campo vem cada chave do JSON (`Destino`, `Caso`, `DV`, `Tipo`, `Código`, `Banco`, ...). Investigados: campo JSON, tabela relacionada ou variáveis? Hoje o JSON é montado fora do `.iBot` e entregue pela fila |
| Anexos | Como distinguir os arquivos a validar dos outros anexos (ofício, PDFs)? Por nome/extensão (`*_GAB109/112/800.txt`, `*_AGENCIAS.txt`...)? |
| Ambientes | Instância de desenvolvimento/homologação para testes, com tarefa de teste dedicada |
| Limites | Rate limit e tamanho máximo de anexo |

### 1.2 Módulo `python/simba/servicenow.py`

Cliente HTTP com `requests`. **Nova dependência**, a ser aprovada.

| Função | Endpoint | Observações |
|---|---|---|
| `_token()` | `POST /oauth_token.do` | Guarda o token em cache até expirar; em 401, renova uma vez e repete |
| `listar_tarefas_pendentes()` | `GET /api/now/table/x_xpi_ofj_judicial_office_task?sysparm_query=...&sysparm_fields=...&sysparm_limit=...&sysparm_offset=...` | Paginação; `sysparm_display_value=false` para receber valores crus |
| `reservar(sys_id)` | `PATCH /api/now/table/x_xpi_ofj_judicial_office_task/{sys_id}` | Marca "em processamento" + work note; só segue se o estado anterior ainda era pendente (evita duas execuções pegarem a mesma tarefa) |
| `montar_caso(tarefa)` | (local) | Converte o registro no dict aceito por `Caso.from_json`; valida campos obrigatórios e falha como erro de negócio se faltar algo |
| `baixar_anexos(sys_id, pasta)` | `GET /api/now/attachment?sysparm_query=table_name=x_xpi_ofj_judicial_office_task^table_sys_id={sys_id}` + `GET /api/now/attachment/{id}/file` | Grava em streaming; confere `size_bytes` (e `hash`, quando disponível); filtra pelos arquivos de validação |
| `anexar(sys_id, arquivo)` | `POST /api/now/attachment/file?table_name=...&table_sys_id=...&file_name=...` | Mesmo conteúdo do `Uploads` do `.iBot`: arquivos de `dadosValidador/<atendimento>` e de suas subpastas de primeiro nível (zip de envio, `.hash`), mais o recibo da transmissão |
| `atualizar_tarefa(sys_id, campos)` | `PATCH /api/now/table/...` | Encerrar, devolver, work notes |

### 1.3 Resultado → ação no ServiceNow

| Resultado | Ação |
|---|---|
| Sucesso (validado + transmitido) | Anexa artefatos → work note com atendimento, hash MD5 e protocolo da transmissão → **encerra a tarefa** |
| `SimbaAviso` no cadastro (ex.: DV inválido, processo > 20 caracteres) | Work note com a mensagem do Simba → estado "devolvida/pendente correção". Sem retry |
| `ArquivosReprovados` | Work note com o texto de Mensagens do Simba (equivale ao `errorHandling` do `.iBot`) → devolvida. Sem retry |
| Dados incompletos na tarefa | Work note listando os campos faltantes → devolvida |
| `StepFailed` (falha técnica depois dos retries) | Work note técnica → estado volta a pendente (nova tentativa no próximo ciclo), com limite de tentativas por tarefa; depois disso, alerta |
| Falha de rede/SN | Retry com backoff; a tarefa fica "em processamento" e é liberada por timeout de reserva (ver 1.4) |

### 1.4 Idempotência e concorrência

- **Reserva:** antes de processar, a tarefa passa para "em processamento" (com o host e o horário na work note). Tarefas presas nesse estado por mais de X minutos voltam a pendente.
- **Validador:** reprocessar é seguro (re-cadastrar sobrescreve, já validado no POC).
- **Transmissão:** **não é idempotente** (ver Fase 2). Gravar no SN o protocolo assim que ele for obtido, antes de encerrar, para que um reprocessamento saiba que já transmitiu.

### 1.5 Segredos e logs

- client_id, client_secret e usuário/senha de integração em variáveis de ambiente ou no **Windows Credential Manager** (`keyring`, outra dependência a aprovar). Nunca no código, no repositório ou no log.
- Logs sem token e sem dados pessoais completos dos investigados (CPF mascarado).

### 1.6 Testes

- Testes de contrato contra a instância de **dev/homologação**, com uma tarefa de teste e anexos fictícios (os mesmos GAB de `tests/gab_ficticio.py`). Marker próprio `servicenow`, rodado só com autorização.
- Mocks só para casos de erro difíceis de provocar (401, 429, timeout); não servem como prova principal.

---

## Fase 2 — Simba Transmissor

### 2.1 Levantamento (no PC da empresa)

| Item | O que descobrir |
|---|---|
| Executável | Caminho, se é Java (provável `simba-transmissor.jar` + launcher, como o Validador) e processos |
| Entrada | Qual pasta/arquivo ele transmite: `dadosValidador/<atendimento>/envio/<atendimento>.zip`? Pasta "Para transmitir" (como o `MoveDirectory` do `.iBot`)? |
| Autenticação | Login/senha, certificado digital, token? Validade e renovação |
| Telas | Sequência completa, mapeada com `scripts/dump_tree.py "<título>"` |
| Conclusão | Mensagem de sucesso, **protocolo/recibo** (tela, arquivo gerado, ambos?) |
| Erros | Mensagens possíveis (pacote inválido, já transmitido, falha de rede, credencial expirada) |
| Histórico | O app mostra pacotes já transmitidos? (essencial para não retransmitir) |
| Homologação | Existe ambiente de teste do MPF/destino? Se não, como testar sem transmitir de verdade? |

### 2.2 Implementação

- **Generalizar `SimbaApp`** (`app.py`) para receber os parâmetros do aplicativo (exe, identificação do processo/jar, tela inicial, títulos conhecidos), mantendo um único `run_step` para Validador e Transmissor. Hoje os parâmetros vêm fixos de `config.SIMBA_EXE` e `screens.PASSO_1`.
- Telas do Transmissor em `screens.py` (ou `screens_transmissor.py`), no mesmo formato `Screen`/`Control`.
- `python/simba/transmissao.py`:
  - `transmitir(app, atendimento) -> ResultadoTransmissao(protocolo, recibo: Path | None)`;
  - autenticação com credencial fora do código;
  - diálogos de erro conhecidos → `SimbaAviso`; falhas de UI → retry via `run_step`.
- **Política de retry da transmissão:** antes de cada nova tentativa, consultar o histórico/recibo. Se já houver transmissão do atendimento, não retransmitir; só recuperar o protocolo. Se não for possível confirmar, **não** repetir automaticamente: devolver a tarefa como "verificar transmissão manualmente".

### 2.3 Testes

- Marker `transmissao`, rodado só com autorização explícita e de preferência em homologação.
- Cobrir: sucesso com protocolo lido, credencial inválida, pacote inválido, queda do app no meio (retry seguro).

---

## Fase 3 — Orquestrador

`python/simba/orquestrador.py` (executável via `python -m simba.orquestrador`):

```
para cada tarefa em servicenow.listar_tarefas_pendentes():
    se não reservar(tarefa): continuar
    pasta = área de trabalho/<sys_id>
    try:
        caso = montar_caso(tarefa); baixar_anexos(tarefa, pasta)
        geracao = fluxo.processar(app, caso, pasta)
        envio   = transmissao.transmitir(app_transmissor, caso.pasta)
        anexar artefatos + recibo; work note (hash, protocolo); encerrar
    except SimbaAviso / dados incompletos: devolver com a mensagem
    except StepFailed: liberar para nova tentativa (com contador)
    finally: fechar Simba Validador e Transmissor; limpar a pasta de trabalho
```

- Uma tarefa por vez (o Simba é uma aplicação de desktop única).
- Log estruturado por tarefa: sys_id, atendimento, etapa, duração e tentativas (`SimbaApp.timings`), resultado. Arquivo de log rotativo.
- Lock de instância única (arquivo de lock ou mutex) para o agendador não iniciar duas execuções.
- **Agendamento:** Agendador de Tarefas do Windows, executando **na sessão do usuário logado** (o JAB precisa de desktop interativo; não funciona como serviço). A máquina não pode bloquear a tela durante a execução.
- Parâmetros: lote máximo por execução, timeout de reserva, limite de tentativas por tarefa.

---

## Fase 4 — Piloto e corte

| # | Atividade |
|---|---|
| 4.1 | Rodar com um lote pequeno de tarefas reais em homologação (ou produção assistida), conferindo cada resultado manualmente |
| 4.2 | Comparar com o WinAutomation: tempo por caso, taxa de sucesso, taxa de reprocessamento |
| 4.3 | Definir o monitoramento: alerta quando uma tarefa estoura o limite de tentativas ou quando o orquestrador fica sem rodar |
| 4.4 | Desligar o `.iBot` e a fila `Simba Validador` |
| 4.5 | Atualizar `docs/estado-atual.md` e o `CLAUDE.md` |

---

## Riscos e pendências

| Risco / pendência | Impacto | Mitigação |
|---|---|---|
| Mapeamento campos SN → JSON ainda desconhecido | Bloqueia a Fase 1 | Levantamento 1.1 com o time SN; validar com tarefas reais |
| Credenciais/certificado do Transmissor | Bloqueia a Fase 2 | Levantamento 2.1; armazenar no Credential Manager |
| Retransmissão duplicada | Alto (envio em duplicidade a órgão externo) | Consultar o histórico antes do retry; gravar o protocolo no SN na hora; sem retry cego |
| JAB exige sessão interativa | Execução agendada pode falhar com a tela bloqueada | Máquina dedicada com sessão logada; política de bloqueio de tela desativada |
| CC 3454 não validado | Casos "Banco" podem falhar | Fase 0.5 antes do piloto |
| Diferenças no PC da empresa (versão do Simba/JRE, pastas) | Seletores quebrados | Suíte de testes na Fase 0; `SIMBA_HOME` |
| OAuth client credentials pode não estar habilitado | Muda o fluxo de token | Suportar password grant como alternativa |
| Anexos grandes / rede instável | Download incompleto | Streaming + conferência de tamanho/hash + retry |

## Ordem sugerida

Fase 0 → Fase 1 (até baixar anexos e rodar `fluxo.processar` com dados reais, ainda sem encerrar a tarefa) → Fase 2 → Fase 3 → Fase 4. O levantamento 1.1 e o 2.1 podem começar em paralelo, já que dependem de outras equipes.

# Simba Validador — Resumo do Fluxo RPA

**Arquivo fonte:** `Simba Validador.iBot`
**Formato:** WinAutomation / Automation Anywhere (Softomotive) — XML `AutxProcess`

## Informações gerais

| Campo | Valor |
|---|---|
| Nome do processo | Simba Validador |
| Criado por | XPCORRETORA\ramon.t7865 |
| Criado em | 2025-05-02 14:36:59 -03:00 |
| Atividade inicial | `Main` |
| Fila de trabalho | `Simba Validador` (objeto `Queue Validador`), tipo `SimbaValidador` |
| Aplicação automatizada | Simba Validador (`simba-validador.exe`, Java/Swing — janelas `SunAwtFrame`/`SunAwtDialog`) |
| Origem dos dados | ServiceNow — tabela `x_xpi_ofj_judicial_office_task` |

## Plugins referenciados

- Essential Toolkit (10.1)
- Universal App Connector (7.0)
- Essential Connectors (10.2)

## Variáveis globais

| Variável | Tipo | Uso |
|---|---|---|
| `Application Path` | Object | `C:\Users\<usuário>\Documents\Programas SIMBA\` |
| `Folder Path` | String | Inicialmente igual a `Application Path`; depois `...\Programas SIMBA\Para validar` |
| `Folder` | String | Nome da pasta do caso: `<Destino>-<Caso>-<DV>` |
| `WorkItemId` | Object | ID do item da fila em processamento |
| `GabOr3454` | String | Campo `Tipo` do JSON: `Banco` ou `Corretora` |
| `Judtask` | String | sys_id da tarefa judicial no ServiceNow (anexos) |

## Dados de entrada (JSON do work item)

O `RequestContent` do item da fila é um JSON desserializado em `Passo 1` com as propriedades:

`Destino`, `Caso`, `DV`, `Tipo`, `Judtask`, `Código`, `Banco`, `CNPJ`, `Responsável`, `Telefone`, `Email`, `Data`, `Processo`, `Vara`, `Tribunal`, `Magistrado`, `Cargo`, `Início`, `Fim`, `Investigados`.

Cada item de `Investigados`: `Investigado_Type` (`PF`/`PJ`), `Investigado_ID` (CPF/CNPJ), `Investigado_Nome`, `Investigado_Info`.

## Telas mapeadas (Universal App Connector)

| Tela | Título da janela | Controles |
|---|---|---|
| Passo 1 | `Validador Bancário - Passo 1` | Computador destino, Número do Caso, DV, Cadastrar, Atendimento a Validar (lista), Validar Arquivos CC 3454, Validar Arquivos GAB |
| Dados do Caso | `Validador Bancário - Dados do Caso` | Abas Instituição Financeira / Processo/Inquérito / Investigados; campos da instituição, responsável, processo, magistrado, afastamento; Adicionar Investigado, Remover Todos, Gravar |
| Investigado | `Investigado` | Pessoa Física/Jurídica, CPF, CNPJ, Nome, Relacionamento Sim/Não, Conta Depósito, B/D/V, Outras informações, Salvar |
| Atenção | `Atencão` | Yes, No |
| Informação | `Informação` (dialog) | OK |
| Passo 2 | sem título | Selecionar Pasta, Continuar, Mensagens |
| Diretório | `Selecione diretório para validação` (dialog) | Pasta, Selecionar Pasta |
| Passo 3 | sem título | Gerar, Fechar, Hash |

## Fluxo

### Main

1. Monta `Application Path` = `C:\Users\<UserName>\Documents\Programas SIMBA\` (também atribuído a `Folder Path`).
2. Monta o caminho do executável: `<Folder Path>Validador\simba-validador.exe`.
3. `GetWorkItems` — até 100 itens `Pending` do tipo `SimbaValidador`. Se `TotalCount` = 0, encerra.
4. Para cada item (`ForEachLoop`):
   1. `PickWorkItem` (status `Pending`) e grava `WorkItemId`. Se vazio, pula para o próximo.
   2. Inicia o Simba Validador e aguarda até 20s por qualquer tela.
      - Tela `Passo 1` encontrada → segue.
      - Caso contrário → `Terminate` com erro: *"Não foi possível abrir o Simba Validador. Pasta:<caminho>."*
   3. Chama **Passo 1** passando o `RequestContent` (JSON).
   4. Seleciona na lista *Atendimento a Validar* o item com texto = `Folder`.
   5. Cria as pastas `<Application Path>Para validar` e `<Application Path>Para transmitir`; `Folder Path` passa a ser `...\Para validar`.
   6. Chama **Passo 2**.
5. Ao final do loop, se a tela `Passo 1` ainda estiver aberta, fecha a aplicação.

### Passo 1 — cadastro do caso

1. Desserializa o JSON e extrai as propriedades.
2. Aguarda a tela `Passo 1`; seleciona *Computador destino* = `Destino` (executado duas vezes); preenche *Número do Caso* = `Caso` e *DV* = `DV`; clica **Cadastrar**.
3. Define `Folder` = `<Destino>-<Caso>-<DV>`, `GabOr3454` = `Tipo`, `Judtask` = `Judtask`.
4. Chama **Dados do Caso** com os dados do JSON.

### Dados do Caso

1. Aguarda a tela e preenche, via `SetFields`: Número/Nome/CNPJ da instituição (`Código`, `Banco`, `CNPJ`), responsável (nome, telefone, email), Data atual, Número do Processo, Vara, Tribunal, Magistrado, Cargo, Início/Fim do afastamento, Descrição do afastamento, Número Bacen/SISBAJUD, Número do Ofício.
2. Chama **Adicionar Investigado**.
3. Foca **Gravar** (duplo clique) e envia teclas; confirma **Yes** na janela *Atenção* e **OK** na janela *Informação*.

### Adicionar Investigado

1. Clica **Remover Todos** (limpa investigados existentes).
2. Para cada investigado: clica **Adicionar Investigado**, aguarda e restaura a janela *Investigado*, e conforme `Investigado_Type`:
   - `PF` → marca Pessoa Física e preenche CPF.
   - `PJ` → marca Pessoa Jurídica e preenche CNPJ.
3. Em ambos: preenche Nome e Outras informações, marca **Relacionamento Sim**, **Conta Depósito**, **B/D/V**, e clica **Salvar**.

### Passo 2 — validação dos arquivos

1. Aguarda a tela `Passo 1` e, conforme `GabOr3454`:
   - `Banco` → clica **Validar Arquivos CC 3454**.
   - `Corretora` → clica **Validar Arquivos GAB**.
2. Aguarda a tela `Passo 2` e chama **Downloads**.
3. Aciona **Selecionar Pasta**; no diálogo *Diretório* informa `<Folder Path>\<Folder>` e confirma.
4. Lê o texto de *Mensagens*:
   - contém `Erro no arquivo` ou `não encontrado` (sem diferenciar maiúsculas) → chama **errorHandling** com a mensagem.
   - caso contrário → clica **Continuar** e chama **Passo 3**.
5. Fecha a tela `Passo 2`.

### Passo 3 — geração e conclusão

1. Aguarda a tela `Passo 3`, clica **Gerar** e depois **Fechar**.
2. Chama **Uploads**.
3. Move `<Folder Path>\<Folder>` para `Folder Path` com `validar` → `transmitir` (`...\Para transmitir`), sobrescrevendo.
4. `UpdateWorkItem` → status `Success`, prioridade `Moderate`, `ResponseContent` = caminho de destino.

### errorHandling

`UpdateWorkItem` → status `Failure`, exceção `Business`, prioridade `High`, `ResponseContent` = texto de *Mensagens*.

### Downloads

1. Cria `<Folder Path>\<Folder>`.
2. Obtém os metadados de anexos da `x_xpi_ofj_judicial_office_task` com sys_id = `Judtask` (propriedade `result`).
3. Baixa cada anexo (`sys_id`) para a pasta, sobrescrevendo.

### Uploads

1. Pasta base: `<Application Path>dadosValidador\<Folder>`.
2. Anexa à tarefa `Judtask` no ServiceNow todos os arquivos da pasta e dos subdiretórios de primeiro nível.

## Pontos de atenção

- `Sisbajud`, `Ofício` e `Descrição` são parâmetros de entrada de *Dados do Caso*, mas não são extraídos do JSON nem passados por `Passo 1` — esses campos ficam vazios.
- `SelectByText` em *Computador destino* é executado duas vezes seguidas com o mesmo valor.
- `SendKeys` em **Gravar** (Dados do Caso) e **Selecionar Pasta** (Passo 2) tem valor estático `oo`.
- Investigados sempre recebem Relacionamento = Sim, Conta Depósito e B/D/V marcados, independentemente do JSON.
- O `MoveDirectory` do Passo 3 usa como destino `...\Para transmitir` (sem a subpasta `<Folder>`), com sobrescrita.
- O `StringFormat` que monta `Para transmitir` no Main não tem `TemplateText` definido.
- Nenhuma ação tem tratamento de erro próprio (`OnErrorAction` = `Inherit`); **errorHandling** só é chamado pelas verificações de *Mensagens* no Passo 2. Timeouts de tela ou erros de UI não atualizam o work item pelo fluxo.

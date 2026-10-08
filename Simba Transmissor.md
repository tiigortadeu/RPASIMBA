# Simba Transmissor — Resumo do Fluxo RPA

**Arquivo fonte:** `Simba Transmissor.iBot`
**Formato:** WinAutomation / Automation Anywhere (Softomotive) — XML `AutxProcess`

## Informações gerais

| Campo | Valor |
|---|---|
| Nome do processo | Simba Transmissor |
| Criado por | XPCORRETORA\ramon.t7865 |
| Criado em | 2025-05-02 14:36:59 -03:00 |
| Atividade inicial | `Main` |
| Fila de trabalho | `Simba Transmissor` (objeto `Qeue Simba Transmissor`), tipo `SimbaTransmissor` |
| Aplicação automatizada | Simba Transmissor 4.6.7 (`simba-transmissor.exe`, Java/Swing — janelas `SunAwtFrame`/`SunAwtDialog`) |
| Destino do envio | Servidor do órgão requisitante (`simba.mpf.mp.br`, produção) |
| Origem dos dados | ServiceNow — tabela `x_xpi_ofj_judicial_office_task` |

## Plugins referenciados

- Essential Toolkit (10.1)
- Universal App Connector (7.0)
- Essential Connectors (10.2)

## Variáveis globais

| Variável | Tipo | Uso |
|---|---|---|
| `Application Path` | Object | `C:\Users\<usuário>\Documents\Programas SIMBA\` |
| `Folder Path` | String | Inicialmente igual a `Application Path`; em *Downloads* passa a `...\dadosValidador\<Folder>\envio` |
| `Folder` | String | Atendimento a transmitir (`<Destino>-<Caso>-<DV>`), do campo `Simba` do JSON |
| `WorkItemId` | Object | ID do item da fila em processamento |
| `Judtask` | String | sys_id da tarefa judicial no ServiceNow (anexos) |
| `Nome da Chave` | Object | Nome do arquivo de chaves (campo `Chave` do JSON) |
| `Senha da Chave` | Object | Senha da chave, vinda do `SensitiveRequestContent` do work item |
| `Application Version` | — | `4.6.7` (declarada, não usada no caminho do executável) |

## Dados de entrada (work item)

`RequestContent` (JSON) com as propriedades `Simba` (atendimento), `Judtask` e `Chave` (nome do arquivo de chaves). A senha da chave vem separada, em `SensitiveRequestContent`.

## Telas mapeadas (Universal App Connector)

| Tela | Título da janela | Controles |
|---|---|---|
| Principal | `Transmissor de Afastamento de Sigilo Bancário` (`SunAwtFrame`) | Escolha o atendimento (filtro), Atendimentos (lista), Selecionar... (chave), Informação (texto de resultado), Enviar dados do Atendimento Selecionado |
| Diretório | qualquer `SunAwtDialog` (o match pelo título `Open` está desligado) | File name (caminho da chave), Open |
| Senha da Chave | `Entre com a senha` | Senha (password), OK |
| Senha incorreta | `Erro` | Mensagem (*A senha deve ter entre 8 e 16 caracteres.*), OK |
| Arquivo não encontrado | `Informação` | Mensagem (*Arquivo não localizado.*), OK |
| Erro no Envio | `Erro` | Mensagem (*Ocorreu um erro interno do sistema e o mesmo será fechado...*), OK |
| Comprovante | `Selecione a pasta para salvar o comprovante de envio` | Folder name, Selecionar Pasta |

## Fluxo

### Main

1. Monta `Application Path` = `C:\Users\<UserName>\Documents\Programas SIMBA\` (também atribuído a `Folder Path`).
2. Monta o caminho do executável: `<Folder Path>Transmissor\simba-transmissor.exe`.
3. `GetWorkItems` — até 100 itens `Pending` do tipo `SimbaTransmissor`. Se `TotalCount` = 0, encerra.
4. Para cada item (`ForEachLoop`):
   1. `PickWorkItem`; desserializa o `RequestContent` e grava `WorkItemId`, `Folder` (= `Simba`), `Judtask`, `Nome da Chave` (= `Chave`) e `Senha da Chave` (= `SensitiveRequestContent`).
   2. Chama **Downloads**.
   3. Inicia o Simba Transmissor e aguarda até 20s por qualquer tela.
      - Tela principal encontrada → segue.
      - Caso contrário → `Terminate` com erro: *"Não foi possível abrir o Simba Transmissor da pasta ...\Transmissor\4.6.7\simba-transmissor.exe"*.
   4. Aguarda o campo *Escolha o atendimento*, foca e digita `Folder` (filtro da lista).
   5. Seleciona o item de índice 0 da lista *Atendimentos*.
   6. Chama **Selecionar Chave**, **Enviar Atendimento** e **Closing**.
5. Ao final do loop, fecha a tela principal.

### Downloads — pacote vindo do ServiceNow

1. `Folder Path` = `<Application Path>dadosValidador\<Folder>\envio`; cria a pasta.
2. Lê os metadados dos anexos da `x_xpi_ofj_judicial_office_task` com sys_id = `Judtask` e baixa cada anexo para `Folder Path`, sobrescrevendo.
3. Cria `<Folder Path>\envio` e move para lá `<Folder>.zip`, `<Folder>.zip.hash` e `<Folder>-tipo-atendimento.txt`, sobrescrevendo.

### Selecionar Chave

1. Monta o caminho da chave: `<Application Path>Chaves\<Nome da Chave>`.
2. Aciona **Selecionar...**; aguarda até 5s o diálogo *Diretório*, preenche *File name* com o caminho e clica **Open**.
3. Se abrir *Arquivo não encontrado* → lê a mensagem, clica **OK** e chama **errorHandling**.
4. Senão, preenche a senha em *Senha da Chave* e clica **OK**.
5. Se abrir *Senha incorreta* → lê a mensagem, clica **OK** e chama **errorHandling**.

### Enviar Atendimento

1. Aciona **Enviar dados do Atendimento Selecionado**.
2. Verifica se a tela *Erro no Envio* está aberta:
   - Sim → lê a mensagem, preenche *Folder name* do diálogo do comprovante com esse texto, clica **Selecionar Pasta**, clica **OK** duas vezes e chama **errorHandling**.
   - Não → encerra a atividade.

### Closing

1. Lê o texto de *Informação* da tela principal.
2. `UpdateWorkItem` → status `Success`, prioridade `High`, `ResponseContent` = texto lido.
3. Anexa à tarefa `Judtask` no ServiceNow os `.pdf` (comprovante) da pasta, sem subpastas.
4. Cria `<Application Path>Transmitidos` e move a pasta do atendimento para lá, sobrescrevendo.

### errorHandling

`UpdateWorkItem` → status `Failure`, exceção `Business`, prioridade `High`, `ResponseContent` = mensagem recebida.

## Regras do Transmissor (extraídas do `simba-transmissor.jar`)

- Só transmite atendimentos que passaram pelo Validador. Um pacote incompleto, inválido ou validado com versão antiga é recusado ("Refaça a validação deste atendimento").
- O CNPJ e o Número do Banco do atendimento precisam ser iguais aos do arquivo de chaves. A chave também precisa ter permissão para o computador destino.
- Avisa quando o atendimento já foi enviado antes: só se reenvia quando o órgão pede revisão.
- No sucesso, gera um comprovante (PDF) na pasta escolhida no diálogo do comprovante.

## Pontos de atenção

- O ramo "Erro no Envio = Sim" preenche o diálogo do comprovante com o texto do erro e é o único que chama **errorHandling**. No ramo de sucesso, o fluxo não trata o diálogo do comprovante, que o Transmissor abre depois de um envio bem-sucedido. A fiação parece invertida ou incompleta.
- A mensagem do `Terminate` cita `Transmissor\4.6.7\simba-transmissor.exe`, mas o `Start` usa `Transmissor\simba-transmissor.exe`.
- A seleção do atendimento é feita pelo índice 0 depois de filtrar, sem conferir o texto do item.
- *Downloads* move o pacote de `...\envio` para `...\envio\envio`, um nível a mais do que o pacote gerado pelo Validador (`dadosValidador\<Folder>\envio`).
- O `StringFormat` que monta `Transmitidos` no Closing não tem `TemplateText` definido.
- **Selecionar...** e **Enviar** são acionados por `SendKeys` com o valor estático `oo`.
- Nenhuma ação tem tratamento de erro próprio (`OnErrorAction` = `Inherit`). Timeouts de tela e falhas de UI não atualizam o work item, e um erro depois do Enviar pode deixar o envio em estado desconhecido.

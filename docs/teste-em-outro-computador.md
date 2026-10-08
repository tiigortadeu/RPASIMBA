# Como testar em outro computador

Guia para montar e testar o RPA Simba (Validador + Transmissor + runners do ServiceNow) numa máquina nova, por exemplo o computador do trabalho. Siga na ordem: cada etapa depende da anterior e tem um critério de "funcionou".

> Os testes abrem e **matam** o Simba Validador e o Simba Transmissor. Não use o Simba durante os testes e salve o que estiver aberto nele antes.

## 1. Pré-requisitos

| Item | Como conferir |
|---|---|
| Windows 10/11, usuário com sessão interativa | O RPA clica na tela via Java Access Bridge: não funciona com a tela bloqueada nem como serviço do Windows |
| Simba Validador e Simba Transmissor instalados | Existem `Documentos\Programas SIMBA\Validador\simba-validador.exe` e `...\Transmissor\simba-transmissor.exe` |
| Java 8 do Simba | `C:\Program Files\Java\jre1.8.0_*` (nesta máquina: `jre1.8.0_503`) |
| Python 3.11 | `py -0p` lista uma versão 3.11. Se não houver, instale pelo python.org ou com `uv python install 3.11` |
| Git | `git --version` |
| Acesso à internet | O Simba consulta `simba.mpf.mp.br` ao abrir |
| JVM em português | Os nomes de botões e diálogos usados pelo RPA estão em pt-BR (`Abrir`, `Nome do arquivo:`, ação `clicar`). Com a JVM em inglês, alguns passos falham |

## 2. Ligar o Java Access Bridge

O RPA lê e aciona as telas do Simba pelo Java Access Bridge (JAB).

1. Num prompt **como o mesmo usuário que vai rodar o RPA**:
   ```
   "C:\Program Files\Java\jre1.8.0_503\bin\jabswitch.exe" -enable
   ```
   Troque `jre1.8.0_503` pela versão instalada.
2. Confira:
   - existe `C:\Windows\System32\WindowsAccessBridge-64.dll`;
   - o arquivo `%USERPROFILE%\.accessibility.properties` contém `assistive_technologies=com.sun.java.accessibility.AccessBridge`.
3. Feche e abra o Simba de novo (o JAB só vale para JVMs abertas depois de ligado).

Se a DLL estiver em outro lugar, defina `RC_JAVA_ACCESS_BRIDGE_DLL` no `.env` (passo 4).

## 3. Baixar o código e instalar

```
git clone https://github.com/tiigortadeu/RPASIMBA.git
cd RPASIMBA
git checkout runners-servicenow
cd python
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Use **sempre** `.venv\Scripts\python`: o `python` do PATH pode ser de outra ferramenta.

Os arquivos `.iBot` não estão no git. Copie-os para a raiz do projeto só se quiser usar o `trace.py`; o RPA não precisa deles.

## 4. Configurar o `.env`

Copie `python\.env.example` para `python\.env` e preencha. Para os testes locais (passos 5 e 6), nada é obrigatório. Para o ServiceNow (passos 7 e 8):

| Variável | Exemplo | Observação |
|---|---|---|
| `SN_INSTANCIA` | `xpinvestimentosdev` | Instância DEV |
| `SN_USUARIO` / `SN_SENHA` | usuário de integração | Precisa ser usuário com senha local (o SSO não funciona para o runner) |
| `RUNNER_ID` | `pc-trabalho-igor` | Aparece nos work items e nos comentários |
| `SIMBA_CHAVES_DIR` | `D:\Simba\Chaves` | Pasta com os arquivos de chaves do Transmissor |
| `SIMBA_SENHA_<CHAVE>` | `SIMBA_SENHA_XP_CORRETORA=...` | Senha de cada arquivo de chaves (nome do arquivo sem extensão, maiúsculo, `_` no lugar de espaços) |
| `SIMBA_HOME` | `C:\Users\fulano\Documents\Programas SIMBA` | Só se o Simba não estiver em `Documentos\Programas SIMBA` |
| `SIMBA_ARQUIVO` | `D:\Simba\Arquivo` | Para onde vão os casos já processados (padrão: `Programas SIMBA\Arquivo`) |
| `SIMBA_TRANSMITIDOS` | `\\servidor\simba\Transmitidos` | Uma pasta por caso com comprovante + zip dos GABs |

**Evite deixar `Programas SIMBA` dentro do OneDrive:** a sincronização já travou arquivo do Simba no meio de uma validação.

O `.env` tem senhas: ele não vai para o git (`.gitignore`). Não o envie por e-mail nem chat.

## 5. Conferir a instalação (sem mexer em dados)

Com a pasta `python` como diretório atual:

```
.venv\Scripts\python -m pytest
```

Abre o Validador, confere os seletores do Passo 1, simula queda e reabertura, e confere o texto dos comentários de erro, a correção automática dos GABs (sem Simba) e o cálculo do DV. **Resultado esperado:** `36 passed` (os grupos `cadastro` e `servicenow` ficam de fora).

Se falhar:

| Sintoma | Causa provável |
|---|---|
| `Timeout aguardando tela 'Passo 1'` | JAB desligado (passo 2) ou Simba fora de `Documentos\Programas SIMBA` (`SIMBA_HOME`). A abertura às vezes demora até 60s |
| `FileNotFoundError ... simba-validador.exe` | `SIMBA_HOME` errado |
| Um controle específico não encontrado | Versão diferente do Simba mudou a tela: rode `.venv\Scripts\python scripts\dump_tree.py "Passo 1"` com o Simba aberto e compare com `simba/screens.py` |
| Muitas linhas `ERROR ... Failed to enumerate window` | Normal: é o JAB sondando janelas que não são Java |

## 6. Testar cadastro, validação e Transmissor (cria um caso fictício local)

```
.venv\Scripts\python -m pytest -m cadastro
```

Grava casos fictícios no `dadosValidador` local, valida GABs fictícios e gera o pacote. Também cobre:
- 6 GABs com defeitos reais (UTF-8 com "ª", BOM, linha curta...), corrigidos automaticamente e aprovados;
- um lote de 10 casos diferentes, arquivados um a um, conferindo que a lista do Validador não cresce;
- no Transmissor, até a senha da chave, **sem enviar**.

**Resultado esperado:** `23 passed` (~5 min).

Para um lote maior: `set SIMBA_TESTE_CASOS=30` e `.venv\Scripts\python -m pytest -m cadastro tests\test_varios_casos.py` (~4 min para 30 casos).

Linhas `FALHOU` no resumo "tempos por etapa" são casos negativos esperados (DV inválido, senha curta etc.), não falhas do teste.

Se houver um arquivo de chaves real na máquina, **não** o use nestes testes: o Transmissor envia para o servidor de produção do órgão.

## 7. Testar o protocolo de fila no ServiceNow DEV

Pré-requisitos no DEV:
- usuário de integração do `.env` com leitura e escrita em `sn_rpa_fdn_work_queue_item`, `x_xpi_ofj_judicial_office_task` e `sys_attachment`;
- uma fila **só para testes** em `sn_rpa_fdn_work_queue` chamada `Simba Runner Teste` (ou outro nome em `SN_FILA_TESTE`), **sem robôs consumindo**.

```
.venv\Scripts\python -m pytest -m servicenow
```

Cria e apaga work items nessa fila: 8 runners disputando 20 itens (nenhum pode ser pego duas vezes), item devolvido com espera, falha de negócio, reaper recolhendo item de runner que caiu, item em envio que nunca volta para a fila, anexo subindo e descendo igual. Esperado: `6 passed`. Se o `.env` não tiver credenciais, os testes aparecem como `skipped`.

## 8. Rodar o runner contra o DEV

Só depois do passo 7 verde, e com um work item de teste preparado no DEV: uma JUDTASK de teste com o JSON do caso na `description`, os GABs anexados e um item na fila do Validador apontando para ela.

```
.venv\Scripts\python -m simba.runner --filas validador --uma-vez
```

`--uma-vez` processa no máximo um item e sai. O log fica no console e em `Documentos\Programas SIMBA\logs\runner.log`.

O que conferir no SN:
- **Sucesso:** o work item fica `Success` com o hash em `response_content`, e a JUDTASK recebe os anexos de `dadosValidador\<atendimento>`.
- **Erro:** o work item fica `Failure` (ou volta a `Pending` se for falha técnica com nova tentativa), e a JUDTASK recebe um comentário `[RPA Simba Validador] ...` dizendo onde parou, o erro e o que fazer.

Para o Transmissor (`--filas transmissor`) vale o mesmo, mas **sem chave real** ele para com o erro de chave/senha, que também vira comentário na tarefa. Não rode o Transmissor com chave real em DEV sem combinar antes: o envio é real.

Para rodar continuamente (como num servidor):

```
.venv\Scripts\python -m simba.runner
```

Pare com `Ctrl+C`; o Simba é fechado ao sair.

## 9. Antes de deixar rodando sozinho

- Desative o bloqueio de tela e a suspensão da sessão usada pelo runner.
- Não use o mouse/teclado nessa sessão enquanto o runner trabalha: um clique fora pode tirar o foco do Simba.
- Um runner por usuário Windows: dois runners no mesmo usuário brigam pelo mesmo Simba.

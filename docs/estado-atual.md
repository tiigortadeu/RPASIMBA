# Simba Validador em Python — Estado Atual

**Data:** 03/10/2026
**Escopo:** migração da automação `Simba Validador.iBot` (WinAutomation) para Python, no diretório `python/`.

## 1. Objetivo e contexto

A automação atual do Simba Validador roda no WinAutomation. Ela tem dois problemas principais:

- quando o Simba dá erro, o fluxo quebra e não se recupera sozinho (timeouts de tela e erros de UI não atualizam o work item);
- é lenta, porque usa esperas fixas, SendKeys e cliques que travam enquanto um modal está aberto.

O POC em Python automatiza o mesmo aplicativo Java (Swing) pelo **Java Access Bridge (JAB)**. Ele reaproveita os seletores do `.iBot`, que são caminhos de índices de filhos no JAB, e acrescenta recuperação automática.

Nesta máquina o POC serviu para provar que a automação é viável. A construção definitiva será feita no PC da empresa, onde o Simba (Validador e Transmissor) já está instalado.

## 2. Arquitetura

```
python/
  simba/
    config.py      caminhos (Documentos real via OneDrive, SIMBA_HOME), timeouts, retries
    jab.py         Bridge (pump JAB em thread daemon) + Element (by_path, wait_for, press/click, texto, seleção)
    screens.py     telas e controles (caminhos JAB copiados do .iBot)
    app.py         SimbaApp: processo, telas, diálogos de aviso, run_step com recuperação
    navigation.py  Passo 1 (destino, caso, DV)
    cadastro.py    Caso/Investigado, Dados do Caso, investigados, Gravar
    validacao.py   Passo 2 (CC 3454 / GAB), resultado da verificação
    geracao.py     Passo 3 (Gerar, conferência do hash, Fechar)
    fluxo.py       processar(app, caso, pasta): fluxo completo
  scripts/dump_tree.py   despeja a árvore JAB das janelas abertas com caminhos no formato do .iBot
  tests/                 testes contra o app real (sem mocks)
```

### 2.1 Camada JAB (`jab.py`)

- `Bridge` é um singleton que roda o message pump do JAB numa thread daemon. A descoberta de JVMs e janelas é assíncrona (~0,2s).
- Só contam janelas **visíveis**: na inicialização, o `Passo 1` já existe escondido atrás do splash `Validador Bancário`.
- `Element.by_path` percorre os índices e confere os papéis (roles). Usa `indexInParent`, e não a posição do filho, porque os dois diferem nos painéis de abas.
- `wait_for` faz polling (`POLL_INTERVAL = 0,1s`) no lugar de esperas fixas.
- **Cliques:** `press()` (foco → espera `focused` → VK_SPACE) para botões que abrem modal; `click()` (ação JAB, cujo nome vem localizado, "clicar") trava ~8s até o modal fechar. Abas são selecionadas pelo `page tab list` (`select_child`).

### 2.2 Robustez (`app.py` — `SimbaApp.run_step`)

Cada etapa roda dentro de `run_step(nome, fn)`:

1. `ensure_ready`: abre o Simba se estiver fechado; reinicia se o Passo 1 não responder.
2. Executa a etapa.
3. Pós-checagem: nenhum diálogo `Aviso`/`Erro` aberto e nenhuma janela desconhecida.
4. Em falha técnica (`ElementNotFound`, `UnexpectedWindow`, `AppNotRunning`, `APIException`, `psutil.Error`, `OSError`), mata o Simba e repete a etapa inteira desde o Passo 1 (`STEP_RETRIES = 2`). Esgotadas as tentativas, levanta `StepFailed`.
5. Erros de negócio (`SimbaAviso`, e a subclasse `ArquivosReprovados`) sobem na hora, **sem retry**, porque reiniciar não corrige dados ruins.

`AppNotRunning` faz uma queda do app falhar na hora, sem esperar o timeout da tela. Os tempos e as tentativas de cada etapa ficam em `SimbaApp.timings`.

### 2.3 Fluxo (`fluxo.processar`)

Duas etapas `run_step`:

| Etapa | O que faz | Equivalente no `.iBot` |
|---|---|---|
| `cadastro` | Passo 1 (destino, caso, DV, Cadastrar) → Dados do Caso (17 campos) → Remover/Adicionar investigados → confere a tabela de investigados → Gravar → "Confirma gravação?" Sim → Informação OK | `Passo 1`, `Dados do Caso`, `Adicionar Investigado` |
| `validar_e_gerar` | seleciona o atendimento → Validar CC 3454 (Banco) ou GAB (Corretora) → seleciona a pasta → espera "Fim da verificação." → Continuar >> → Gerar → confere o hash MD5 do zip → Fechar | `Passo 2`, `Passo 3` |

A validação e a geração ficam na mesma etapa porque o Passo 3 só abre a partir de um Passo 2 aprovado. **Fechar encerra o processo Simba**; a próxima etapa reabre o app via `ensure_ready`.

Saídas no disco: `dadosValidador/<Destino>-<Caso>-<DV>/`, com o pacote em `envio/<atendimento>.zip` e o `.zip.hash`.

## 3. Contrato de entrada

Mesmo JSON do work item do `.iBot` (`Caso.from_json`). Exemplo em `python/tests/data/caso_teste.json`:

| Chave | Uso |
|---|---|
| `Destino`, `Caso`, `DV` | Passo 1; atendimento = `<Destino>-<Caso>-<DV>` |
| `Tipo` | `Banco` → CC 3454; `Corretora` → GAB |
| `Judtask` | sys_id da tarefa no ServiceNow (ainda não usado pelo POC) |
| `Código`, `Banco`, `CNPJ` | Instituição financeira |
| `Responsável`, `Telefone`, `Email` | Responsável |
| `Data`, `Processo`, `Vara`, `Tribunal`, `Magistrado`, `Cargo`, `Início`, `Fim` | Processo/afastamento |
| `Sisbajud`, `Ofício`, `Descrição` | Opcionais (o `.iBot` não preenchia) |
| `Investigados[]` | `Investigado_Type` (PF/PJ), `Investigado_ID`, `Investigado_Nome`, `Investigado_Info` |

## 4. O que já está validado

Todos os testes rodam contra o Simba real instalado (sem mocks). Os testes que criam atendimentos usam o marker `cadastro` e só rodam com autorização.

| Área | Cenário | Teste | Resultado |
|---|---|---|---|
| Abertura | Abre o Simba e mostra o Passo 1 | `test_smoke.py::test_abre_simba_e_mostra_passo1` | OK |
| Seletores | Todos os controles do Passo 1 encontrados | `test_selectors.py::test_controle_passo1_encontrado` | OK |
| Navegação | Preenche o Passo 1 e lê de volta | `test_navigation.py::test_preenche_passo1_e_le_de_volta` | OK |
| Navegação | Selecionar o destino atualiza o órgão | `test_navigation.py::test_selecionar_destino_atualiza_orgao` | OK |
| Navegação | Destino inexistente falha depois dos retries | `test_navigation.py::test_destino_inexistente_falha_apos_retentativas` | OK |
| Recuperação | Reabre quando o Simba foi fechado | `test_recovery.py::test_reabre_quando_simba_foi_fechado` | OK |
| Recuperação | Reinicia e repete a etapa quando o app cai no meio | `test_recovery.py::test_reinicia_e_repete_etapa_quando_app_cai_no_meio` | OK |
| Cadastro | DV inválido → `SimbaAviso`, sem retry | `test_cadastro.py::test_dv_invalido_falha_com_mensagem_do_simba_sem_retentar` | OK |
| Cadastro | Preenche Dados do Caso e investigados | `test_cadastro.py::test_preenche_dados_do_caso_e_investigados` | OK |
| Cadastro | Processo com mais de 20 caracteres falha ao gravar | `test_cadastro.py::test_processo_com_mais_de_20_caracteres_falha_ao_gravar` | OK |
| Cadastro | Grava e o atendimento aparece no Passo 1 | `test_cadastro.py::test_grava_caso_e_atendimento_aparece_no_passo1` | OK |
| Validação GAB | Pasta sem arquivos → reprovada e volta ao Passo 1 | `test_validacao.py::test_pasta_sem_arquivos_e_reprovada_e_volta_ao_passo1` | OK |
| Validação | Atendimento inexistente falha sem retry | `test_validacao.py::test_atendimento_inexistente_falha_sem_retentar` | OK |
| Validação GAB | GAB fictício válido → aprovado | `test_validacao.py::test_gab_ficticio_valido_e_aprovado` | OK |
| Validação GAB | GAB112 sem um investigado → reprovado | `test_validacao.py::test_gab112_sem_um_investigado_e_reprovado` | OK |
| Fluxo completo | Cadastro → validação → pacote de envio com hash conferido | `test_fluxo.py::test_processa_caso_do_cadastro_ao_pacote_de_envio` | OK — ~4s por caso, 40 execuções seguidas sem falha |

Caso de teste fictício: `002-PF` / caso `013110` / DV `03` (gravado no `dadosValidador` local). Os arquivos GAB fictícios são gerados por `tests/gab_ficticio.py`: GAB112 posicional de 307 caracteres por linha, com layout do enum `CamposGab112` do `simba-validador.jar`; GAB109 e GAB800 vazios.

### Ainda não validado

- Aprovação de arquivos **CC 3454** (tipo `Banco`).
- Arquivos **reais** vindos do ServiceNow (só fictícios até agora).
- Execução no **PC da empresa** (seletores, tempos, caminho do Simba).
- **Transmissão** (Simba Transmissor) e **integração com o ServiceNow**: fora do escopo do POC até aqui.

## 5. Diferenças em relação ao `.iBot`

**Corrigido / melhorado**

- `Sisbajud`, `Ofício` e `Descrição` agora são lidos do JSON e preenchidos (no `.iBot` ficavam vazios).
- Sem `SendKeys` estáticos ("oo") e sem seleção duplicada do Computador destino.
- Toda falha técnica tem retry com restart; o `.iBot` não tratava erros de UI.
- O hash exibido no Passo 3 é conferido contra o MD5 do zip gerado.
- O resultado da validação é decidido por "Fim da verificação." + Continuar habilitado + ausência de frases de erro, e não só pelas frases de erro.
- Investigados conferidos na tabela depois do cadastro.

**Fora do escopo, por decisão (ainda não implementado)**

- Fila de trabalho (`GetWorkItems` / `PickWorkItem` / `UpdateWorkItem`).
- `Downloads` (anexos da `x_xpi_ofj_judicial_office_task` → pasta do caso) e `Uploads` (conteúdo de `dadosValidador/<atendimento>` → anexos da tarefa).
- `MoveDirectory` de "Para validar" para "Para transmitir".
- Transmissão.

## 6. Peculiaridades do Simba (descobertas no POC)

- A lista do Computador destino carrega ~0,6s depois de o Passo 1 aparecer.
- Número do Caso é um campo mascarado de 6 dígitos; o DV tem 2 caracteres. As leituras voltam com espaços.
- Número do Processo aceita no máximo 20 caracteres: o número CNJ vai só com dígitos.
- Re-cadastrar um caso existente abre o formulário vazio, e gravar de novo sobrescreve (sem duplicar). Por isso o retry do cadastro é seguro.
- Passo 2 e Passo 3 não têm título de janela; são distinguidos por um label marcador (`Screen.marker`).
- O Simba remove zeros à esquerda do MD5 (na tela e no `.zip.hash`), então a comparação é numérica.
- **Fechar** no Passo 3 encerra todo o processo Simba.
- As regras e mensagens do validador ficam em `br/mp/mpf/spea/simba/validador/{enums,rules,carga}` dentro do jar.
- O `.iBot` usa `C:\Users\<usuário>\Documents` fixo; o POC resolve a pasta Documentos real (redirecionada pelo OneDrive), que pode ser sobrescrita por `SIMBA_HOME`.

## 7. Como rodar

No diretório `python/`, sempre com o venv do projeto:

```
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest                       # não roda os testes "cadastro"
.venv\Scripts\python -m pytest -m cadastro           # cria atendimentos locais (com autorização)
.venv\Scripts\python -m pytest tests/test_recovery.py -k queda
.venv\Scripts\python scripts\dump_tree.py "Passo 1"
```

Dependências: `java-access-bridge-wrapper`, `psutil`, `pytest` (e `pywin32`, usado em `config.py`/`app.py`). Os testes matam qualquer instância aberta do Simba e fecham o app no final.

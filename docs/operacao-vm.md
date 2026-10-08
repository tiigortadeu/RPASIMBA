# RPA Simba — Operação na VM

Guia para colocar o RPA de pé numa VM Windows e operar no dia a dia. Leia a seção **Pontos de atenção** antes do primeiro lote real.

---

## 1. Pontos de atenção

### Sessão do Windows
- O RPA controla o Simba pela tela (Java Access Bridge). **A sessão do usuário do RPA precisa estar logada e desbloqueada o tempo todo.**
- Desligue proteção de tela, bloqueio automático e suspensão/hibernação (Configurações → Energia: "Nunca").
- Se o acesso for por Área de Trabalho Remota: **minimizar ou desconectar a janela da RDP pode parar a automação.** Deixe a janela da RDP aberta (pode ficar atrás de outras janelas da sua máquina) ou use a console da VM.
- **Não use a VM enquanto um lote roda.** Um clique em outra janela tira o foco do Simba e a etapa em andamento falha (ela é repetida, mas o lote fica mais lento). Acompanhe pelo painel do console sem clicar em nada fora dele.

### Uma execução por vez
- O Automia (`bot.py`) e o console disparam o mesmo runner. **Nunca rode os dois ao mesmo tempo**: duas execuções na mesma VM disputam o Simba.
- O console não deixa iniciar um lote se já houver outro rodando por ele; o Automia não é verificado, então combine quem dispara.

### Limite do ServiceNow
- O usuário de integração é **bloqueado acima de 100 requisições por minuto** (soma de todos os processos que usam o usuário).
- O runner respeita `SN_REQUISICOES_POR_MINUTO` (70 numa VM). Com mais de uma VM no mesmo usuário, divida: a soma precisa ficar abaixo de 100.
- O botão "Baixar casos" do console fica bloqueado durante um lote pelo mesmo motivo. Scripts avulsos contra o ServiceNow também contam.

### Envio ao órgão
- **Enviar transmite de verdade ao órgão.** Depois do Enviar o RPA nunca repete sozinho; uma falha nesse ponto vira "Ação manual" para conferência.
- O RPA não reenvia um atendimento cuja JUDTASK já tem comprovante (`evidence_attachment`).
- **Na dúvida, rode em simulação** (opção ligada por padrão no console): valida, seleciona a chave e para antes do Enviar, sem gravar nada no ServiceNow.

### Simba
- Validador e Transmissor instalados e apontando para o **ambiente de produção** (a tela inicial não pode mostrar "Acessando ambiente de testes").
- Um atendimento por cooperação técnica em cada lote (o console bloqueia duplicados).
- Órgãos que só aceitam o leiaute CC 3454 (ex.: 056-PCPR, 041-TST, 013-PCMG) falham com mensagem clara — não são tratados pelo RPA.

### Chaves
- Arquivos `.ASB` na pasta `SIMBA_CHAVES_DIR` e o CSV de senhas em `SIMBA_CHAVES_CSV`. Restrinja o acesso dessa pasta ao usuário do RPA.
- Sem chave completa para o órgão (arquivo + senha), o caso falha como "Ação manual" e o lote segue. Confira a tela **Configuração** antes de cada lote.

### Work items e lista do Bacen
- `SIMBA_ITENS_DESDE` define a data a partir da qual os work items são processados. Itens anteriores (inclusive presos de robôs antigos) ficam parados — não altere sem combinar.
- A lista do Bacen (`SIMBA_LISTA_BACEN`) é a referência do que precisa ser respondido. O escopo do RPA são as requisições com envio pelo **Simba**; as de STA aparecem só para conferência.

### Dados sensíveis
- As pastas do Simba (`Trabalho`, `Arquivo`, `Transmitidos`, `Simulacao`) e as exportações do console contêm dados reais de investigados. Não copie para fora da VM; apague as pastas de simulação quando não forem mais úteis.
- O `.env` e o CSV de chaves têm senhas: nunca versione nem envie por e-mail/chat.

---

## 2. Instalação

### 2.1 Pré-requisitos
| Item | Como conferir |
|---|---|
| Windows com o usuário do RPA logado | — |
| Java 8 (JRE) instalado | `java -version` |
| Java Access Bridge ativado | `jabswitch -enable` (no `bin` do Java) e reiniciar a sessão |
| Simba Validador e Simba Transmissor (produção) | abrir cada um e conferir a tela inicial |
| Python 3.12 | `py -3.12 --version` |
| Acesso ao ServiceNow e ao índice interno de pacotes (para o `xpi-automia`) | — |

### 2.2 Código
```cmd
git clone https://github.com/tiigortadeu/RPASIMBA.git C:\RPA\RPASIMBA
cd C:\RPA\RPASIMBA\python
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```
O `xpi-automia` vem do índice interno (só é usado pelo `bot.py`, a entrada do Automia). Fora da rede interna, instale os demais pacotes e siga.

### 2.3 Configuração (`.env`)
Copie `.env.example` para `.env` na mesma pasta e preencha. O essencial:

| Variável | Exemplo / observação |
|---|---|
| `SN_INSTANCIA`, `SN_USUARIO`, `SN_SENHA` | instância e usuário de integração (basic auth) |
| `SN_REQUISICOES_POR_MINUTO` | `70` com uma VM |
| `RUNNER_ID` | nome desta VM nos work items, ex.: `vm-simba-01` |
| `SIMBA_ITENS_DESDE` | data de corte dos work items, `AAAA-MM-DD` |
| `SIMBA_HOME` | pasta "Programas SIMBA" |
| `SIMBA_VALIDADOR_EXE`, `SIMBA_TRANSMISSOR_EXE` | caminho completo dos `.exe` (obrigatório se a versão fica numa subpasta, ex.: `Validador\5.8.7`) |
| `SIMBA_CHAVES_DIR`, `SIMBA_CHAVES_CSV` | pasta dos `.ASB` e CSV `NOME DA CHAVE;SENHA;RESPONSÁVEL` |
| `SIMBA_LISTA_BACEN` | planilha do Bacen (aba com `NUM_CTRL_CCS`) |
| `SIMBA_TRANSMITIDOS` | onde ficam comprovante + zip dos GABs de cada caso (pode ser pasta de rede) |

As demais variáveis têm padrão e estão comentadas no `.env.example`. Valor vazio vale como "não definido".

### 2.4 Verificação
```cmd
cd C:\RPA\RPASIMBA\python
.venv\Scripts\python testar_servicenow.py
.venv\Scripts\pytest
.venv\Scripts\python -m console
```
1. `testar_servicenow.py`: deve terminar com "TESTE ServiceNow OK" (só leitura).
2. `pytest`: testes padrão. Alguns abrem o Simba Validador de verdade — não mexa na VM enquanto rodam.
3. Console (abre o navegador em http://localhost:8080): na tela **Configuração**, tudo "OK" em Ambiente; em Chaves, os órgãos que serão processados como "OK"; a lista do Bacen com o total de requisições esperado.

### 2.5 Primeiro uso (ordem obrigatória)
1. **Baixar casos do ServiceNow** no console.
2. Em **Tarefas**, filtre Situação = Pendente e selecione ~10 casos de órgãos com chave "OK". Rode com **Simulação ligada**. Confira no painel de Execução e no log do lote.
3. Selecione **1 caso** e rode com a simulação **desligada** (envio real). Confira:
   - work item com Sucesso e JUDTASK com comprovante (ServiceNow);
   - `SIMBA_TRANSMITIDOS\<atendimento>` com o PDF do comprovante e o `<atendimento>_GABs.zip`.
4. Lote real de ~10 casos; depois lotes de 300 a 500 casos por play.

---

## 3. Operação do dia a dia

1. Abrir o console: `.venv\Scripts\python -m console` (pode criar um atalho na área de trabalho).
2. **Baixar casos do ServiceNow** (o retrato só muda quando você clica).
3. **Dashboard**: pendentes, vencidas, erros mais frequentes.
4. **Tarefas**: filtrar (Envio = Simba, Situação, Prazo), selecionar e **Executar selecionados**. Leia os avisos da janela de confirmação (chaves faltando, duplicados).
5. Acompanhe o painel **Execução** (no Dashboard). Para encerrar antes do fim: **Parar após o caso atual**.
6. Ao terminar: **Baixar casos** de novo e **Exportar Excel** para prestar contas (abas Resumo, Lista, Erros, Sem work item, Fora da lista).

Fechar o console não interrompe um lote em andamento; ao reabrir, o painel mostra o lote atual.

### Reprocessar erros
- Erros de **Dados/arquivos** (ex.: "Número da Vara com mais de 10 caracteres", "CPF/CNPJ sem relacionamento no período"): corrigir a tarefa no ServiceNow; depois selecionar o caso (situação Falha) e executar de novo.
- **Ação manual** (chave/senha, falha depois do Enviar): resolver a causa (Configuração) ou conferir no Simba/órgão se o envio aconteceu antes de reprocessar.
- **Técnico (nova tentativa)**: o RPA tenta de novo sozinho, até 3 vezes.

---

## 4. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Etapas falhando com "Timeout aguardando tela" em sequência | sessão bloqueada, RDP minimizada, alguém usando a VM | desbloquear a sessão, deixar a RDP aberta, não usar a VM durante o lote |
| "Arquivo de chaves do órgão X não encontrado" / "Senha ... vazia" | `.ASB` ausente na pasta ou linha do CSV incompleta | conferir a tela Configuração; ajustar pasta/CSV (o runner relê o CSV a cada envio) |
| "Arquivo de chaves inválido ou senha incorreta" | senha errada no CSV ou `.ASB` corrompido | corrigir o CSV; testar o caso em simulação |
| "O Simba não libera 'Validar Arquivos GAB' ... só habilita CC 3454" | órgão exige leiaute CC 3454 | fora do escopo do RPA: tratar manualmente |
| "O ServiceNow não gravou status ... papel sn_rpa_fdn.rpa_robot" | usuário de integração sem permissão no work item | pedir o papel ao time do ServiceNow |
| HTTP 429 / acesso bloqueado no ServiceNow | limite de requisições estourado | parar scripts paralelos; conferir `SN_REQUISICOES_POR_MINUTO` |
| Lote "interrompido" no painel | o processo do runner terminou de forma inesperada (VM reiniciou, erro do Python) | ver o log do lote (`Console\lotes\lote_*.log`); itens em andamento são devolvidos pelo reaper em ~15 min |
| Console não abre | porta ocupada ou console já aberto | fechar a outra instância ou usar `CONSOLE_PORTA` |

## 5. Onde estão os registros

| O quê | Onde |
|---|---|
| Log do runner (rotativo, 10 × 10 MB) | `SIMBA_LOGS\runner.log` (padrão `Programas SIMBA\logs`) |
| Log de cada lote disparado pelo console | `Programas SIMBA\Console\lotes\lote_<data>.log` (+ `.json` com os work items) |
| Andamento do lote atual | `Programas SIMBA\Console\andamento.json` |
| Retrato do ServiceNow / cache da lista | `Programas SIMBA\Console\retrato.json`, `lista_bacen.json` |
| Exportações | `Programas SIMBA\Console\exportacoes\` |
| Comprovantes e GABs enviados | `SIMBA_TRANSMITIDOS\<atendimento>\` |
| Casos processados (saem das listas do Simba) | `SIMBA_ARQUIVO\<atendimento>\` |
| Simulações | `Programas SIMBA\Simulacao\<data>\` |

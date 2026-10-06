# RPA Simba — Documentação completa

**Atualizado em:** 05/10/2026
**Código:** `python/simba/` · **Testes:** `python/tests/`
**Documentos relacionados:**
- [teste-em-outro-computador.md](teste-em-outro-computador.md): instalar e testar numa máquina nova;
- [analise-producao.md](analise-producao.md): o que falta, riscos e checklist de produção;
- [Simba Validador.md](../Simba%20Validador.md) e [Simba Transmissor.md](../Simba%20Transmissor.md): os fluxos antigos (`.iBot`).

---

## 1. O que o sistema faz

Automatiza o atendimento de ofícios judiciais de afastamento de sigilo bancário no **Simba**, o sistema do MPF:

1. O **ServiceNow** decide quais casos entram no RPA. Ele guarda o JSON do caso e os arquivos (GABs) anexados à tarefa judicial (JUDTASK) e coloca um work item na fila do RPA Hub.
2. Um **runner** (programa Python numa sessão Windows) pega o item na fila, baixa os arquivos e opera o **Simba Validador**: cadastra o caso, valida os arquivos, gera o pacote de envio e devolve o resultado ao ServiceNow.
3. O fluxo do ServiceNow cria a tarefa de transmissão. Um runner opera o **Simba Transmissor**: carrega a chave da instituição e envia o pacote ao órgão. Depois guarda o comprovante e devolve o resultado.
4. Qualquer parada é registrada na JUDTASK com o ponto onde parou, o erro e o que fazer.

```
                  ServiceNow (fonte de verdade)
   JUDTASK: JSON do caso + GABs anexos        Filas do RPA Hub
   ▲ anexos, comentários, comprovante         "Simba Validador" / "Simba Transmissor"
   │                                          ▲ reserva / status / etapa
   │ REST (Table + Attachment API)            │
┌──┴──────────────────────────────────────────┴──────────────────────┐
│ runner 1 … runner N  (1 por sessão Windows, 1 caso por vez)        │
│   fila.py: reserva, heartbeat, reaper   notificacao.py: comentários│
│   Validador: cadastro → validação (+ correção) → geração           │
│   Transmissor: chave + senha → envio → comprovante                 │
│   JAB (Java Access Bridge) ── Simba Validador / Transmissor (Java) │
└─────────────────────────────────────────────────────────────────────┘
```

## 2. Tecnologias

| Camada | Tecnologia | Uso |
|---|---|---|
| Linguagem | Python 3.11 | Todo o RPA |
| Automação de tela | **Java Access Bridge** (`java-access-bridge-wrapper` 2.0, `WindowsAccessBridge-64.dll`) | Lê e aciona os controles Swing do Simba por caminho de acessibilidade, os mesmos caminhos do `.iBot` |
| Windows | `pywin32` (pasta Documentos real, mensagens de teclado), `psutil` (processos do Simba) | Abrir, matar e monitorar o Simba |
| ServiceNow | `requests`: Table API, Attachment API, basic auth de usuário de integração | Filas, tarefas, anexos, comentários |
| Configuração | `python-dotenv` (`python/.env`) | Instância, credenciais, pastas, senhas das chaves |
| Testes | `pytest` | Testes contra o Simba real e contra o ServiceNow DEV |
| Aplicações | Simba Validador 5.8.7 e Simba Transmissor 4.6.7 (Java 8, Swing) | Aplicações do MPF automatizadas |
| Orquestração | Filas do **RPA Hub** do ServiceNow (`sn_rpa_fdn_work_queue_item`) | As mesmas que os robôs Intellibot (`.iBot`) consumiam |

## 3. Módulos

| Módulo | Responsabilidade |
|---|---|
| `config.py` | Caminhos (Documentos real, inclusive redirecionado pelo OneDrive), timeouts, parâmetros da fila, leitura do `.env` |
| `jab.py` | Ponte JAB: janelas, elementos por caminho, espera por polling, clique (`press`/`click`), texto, seleção |
| `screens.py` | Telas e controles do Validador e do Transmissor (caminhos JAB) |
| `app.py` | `SimbaApp(programa)`: abre/fecha/mata o programa, encontra telas, converte diálogos de erro em `SimbaAviso` e executa etapas com recuperação (`run_step`) |
| `navigation.py`, `cadastro.py` | Passo 1 e Dados do Caso / investigados / Gravar |
| `validacao.py` | Passo 2: validação CC 3454 (Banco) ou GAB (Corretora) |
| `correcao.py` | Correção automática de defeitos mecânicos dos GABs reprovados |
| `geracao.py` | Passo 3: gera o pacote e confere o hash |
| `transmissao.py` | Transmissor: atendimento, chave + senha, envio, zip dos GABs |
| `fluxo.py` | `processar` (Validador inteiro) e `transmitir` (Transmissor inteiro) |
| `arquivo.py` | Move `dadosValidador/<atendimento>` para o arquivo depois de cada caso |
| `servicenow.py` | Cliente REST com retry |
| `fila.py` | Reserva de work items entre N runners, heartbeat, conclusão/falha, reaper |
| `notificacao.py` | Texto e gravação dos comentários e notas na JUDTASK |
| `runner.py` | Programa `python -m simba.runner`: loop, handlers do Validador e do Transmissor, tratamento de erros |

---

## 4. Fluxo passo a passo

### 4.1 Como o trabalho chega

O fluxo do ServiceNow (não alterado pelo projeto) cria os work items:
- `SimbaValidador_JUDTASKnnnnnnn` na fila **Simba Validador**: o `request_content` traz o JSON do caso; se vier vazio, o runner lê a `description` da tarefa.
- `SimbaTransmissor_JUDTASKnnnnnnn` na fila **Simba Transmissor**: o `request_content` traz `{Judtask, Simba, Chave}`, isto é, a tarefa de transmissão, o atendimento e o arquivo de chaves.

Quando o item do Validador termina com `success`, o próprio ServiceNow encerra a tarefa do Validador e encaminha a tarefa do Transmissor.

JSON do caso (mesmas chaves do `.iBot`): `Destino`, `Caso`, `DV`, `Tipo` (`Banco` → CC 3454, `Corretora` → GAB), `Judtask`, `Código`, `Banco`, `CNPJ`, `Responsável`, `Telefone`, `Email`, `Data`, `Processo`, `Vara`, `Tribunal`, `Magistrado`, `Cargo`, `Início`, `Fim`, opcionais `Sisbajud`, `Ofício`, `Descrição`, e `Investigados[]` (`Investigado_Type` PF/PJ, `Investigado_ID`, `Investigado_Nome`, `Investigado_Info`). O atendimento no Simba se chama `<Destino>-<Caso>-<DV>`, por exemplo `001-MPF-006638-18`.

### 4.2 O runner e a fila

`python -m simba.runner [--filas validador,transmissor] [--uma-vez]`. Em loop: reaper (a cada 5 min) → um item de cada fila por volta → espera 30s se as filas estiverem vazias.

**Reserva** (`fila.py`). O Table API não tem update condicional, então:
1. Lista até 50 itens `pending`, não travados e fora do `deferred_till`, e sorteia entre os 20 mais antigos.
2. Relê o item e grava `status=in_progress`, `locked=true`, `remarks=runner=<RUNNER_ID>;token=<uuid>`, `attempts_count+1`.
3. Espera 2s e relê. Se o `remarks` não for o seu, outro runner venceu e ele desiste daquele item.

Com 8 processos disputando 20 itens, o teste confere que cada item é pego uma única vez.

**Heartbeat:** a cada 60s o runner grava a etapa atual em `stage`. Isso renova o lease (`sys_updated_on`) e confirma que a reserva continua sua.
**Reaper:** item `in_progress` sem heartbeat há 15 min foi abandonado (runner caiu ou máquina reiniciou). Ele volta para `pending` ou vira `failure` se as tentativas acabaram. Item do Transmissor parado em `enviando` ou `registrando` **nunca volta**: vira falha para verificação manual.

### 4.3 Validador (item da fila Simba Validador)

| Etapa (`stage`) | O que acontece |
|---|---|
| `reservado` | Lê o JSON → `Caso`. JSON inválido ou incompleto → falha de negócio |
| `baixando` | Baixa todos os anexos da JUDTASK para `Trabalho\<work item>\<atendimento>\`, conferindo o tamanho. Sem anexos → falha de negócio |
| `validando` | `fluxo.processar` (ver abaixo) |
| `anexando` | Sobe para a JUDTASK os arquivos de `dadosValidador\<atendimento>` e das subpastas (pacote `envio\*.zip`, `.zip.hash`, `-tipo-atendimento.txt`, cópias validadas em `arqtxt\`, relatório). Não duplica: pula o que já existe com o mesmo nome e tamanho |
| `concluido` | `success` com o hash; se houve correção automática, uma nota de trabalho de auditoria na JUDTASK |
| sempre | Fecha o Validador e **move `dadosValidador\<atendimento>` para `Arquivo\`**, para o caso sumir da lista suspensa |

`fluxo.processar` executa duas etapas `run_step`:
1. **cadastro:** Passo 1 (Computador destino, Número do Caso, DV, Cadastrar) → Dados do Caso (17 campos) → remove e adiciona os investigados, conferindo a tabela → Gravar → "Confirma gravação?" Sim → OK. Recadastrar um caso existente sobrescreve, então repetir é seguro.
2. **validar_e_gerar:** seleciona o atendimento → Validar CC 3454 ou GAB → escolhe a pasta → espera "Fim da verificação.". Aprovado significa Continuar habilitado e nenhuma frase de erro.
   - Se reprovou, aplica a **correção automática** (seção 6) e valida de novo uma vez.
   - Depois: Continuar → Gerar → confere o MD5 exibido com o do zip → Fechar (o Simba encerra).

### 4.4 Transmissor (item da fila Simba Transmissor)

| Etapa | O que acontece |
|---|---|
| `reservado` | Lê `{Judtask, Simba, Chave}`. **Anti-duplicidade:** se a tarefa já tem `evidence_attachment` (comprovante), conclui sem enviar |
| (verificação) | Arquivo de chaves `SIMBA_CHAVES_DIR\<Chave>` e senha `SIMBA_SENHA_<CHAVE>` no `.env`. Se faltar algum → falha que exige ação manual |
| `baixando` | Baixa da tarefa `<at>.zip`, `<at>.zip.hash` e `<at>-tipo-atendimento.txt` para `dadosValidador\<at>\envio\`, mais as cópias validadas `<at>_*.txt` para o zip dos GABs. Pacote incompleto → falha de negócio |
| (Transmissor) | Reabre o Transmissor (ele só lê a lista ao abrir) → seleciona o atendimento pelo nome exato. Recusa se não estiver na lista, não estiver validado ou **já tiver sido enviado** → Selecionar... → diálogo `Abrir` com o arquivo de chaves → senha → espera o Enviar habilitar |
| `enviando` | Gravada no ServiceNow **antes** do clique em Enviar → envia → salva o comprovante → mensagem de sucesso. Qualquer falha técnica a partir daqui → `TransmissaoIncerta`, sem nova tentativa |
| `registrando` | Sobe o comprovante para a JUDTASK no campo `evidence_attachment` (anexo em `ZZ_YYx_xpi_ofj_judicial_office_task` + PATCH do campo) → `success` |
| sempre | Fecha o Transmissor e move `dadosValidador\<at>` para `Arquivo\` |

**Pasta do caso transmitido:** `Transmitidos\<atendimento>\`, uma por caso, com o **comprovante em PDF** e o **`<atendimento>_GABs.zip`** lado a lado:

```
Transmitidos\
  001-MPF-006638-18\
    <comprovante>.pdf
    001-MPF-006638-18_GABs.zip      (GAB109, GAB112, GAB800 validados)
  002-PF-013110-03\
    ...
```

---

## 5. Tratamento de erros

### 5.1 Níveis de recuperação

| Nível | Onde | O que faz |
|---|---|---|
| Etapa do Simba | `SimbaApp.run_step` | Falha técnica (tela não encontrada, janela inesperada, Simba caiu, erro JAB) → mata o Simba, reabre e repete a etapa, até 3 vezes no total. Abertura lenta tolerada até 60s |
| Work item | `runner` + `fila.devolver` | Etapa ainda falhando, ServiceNow fora do ar ou disco → item volta a `pending` com espera de 5 min × tentativa, até 3 tentativas; depois, falha definitiva |
| Runner | loop do `runner` | Erro fora de um item (ex.: ServiceNow fora do ar ao reservar) → log e continua |
| Entre runners | `fila.reaper` | Runner que caiu → o item é recolhido por outro runner após 15 min |

### 5.2 Classificação e o que o usuário vê

Toda parada vira **status no work item** e **registro na JUDTASK**:

| Situação | Work item | Na JUDTASK | Orientação ao usuário |
|---|---|---|---|
| Erro do Simba (DV inválido, processo com mais de 20 caracteres, arquivos reprovados), JSON/anexos inválidos, pacote incompleto | `failure`, `business` | **Comentário** "Erro de validação/dados" | Corrigir os dados ou arquivos e reenviar |
| Transmissão incerta, falha no registro do comprovante, chave/senha ausentes, tentativas esgotadas | `failure`, `application` | **Comentário** "Falha que exige tratamento manual" | Verificar e tratar manualmente |
| Falha técnica com nova tentativa | `pending` (adiado) | **Nota de trabalho** | Nenhuma ação |
| Runner caiu (reaper) | `pending` ou `failure` | Nota ou comentário, conforme o caso | Idem |
| Correção automática aplicada | `success` | **Nota de trabalho** com o que foi alterado | Nenhuma ação (auditoria) |

Exemplo de comentário:

```
[RPA Simba Validador] Erro de validação/dados
Parou em: cadastro e validação no Simba Validador
Erro: Erro no arquivo: GAB112, linha: 0, erro: O investigado com CPF/CNPJ 11222333000181 não foi encontrado no arquivo cadastral(gab112).
Detalhe: último passo no Simba: validar_e_gerar (falhou após 1 tentativa(s))
O que fazer: Corrija os dados ou os arquivos da tarefa e reenvie para o RPA. O RPA não tentará de novo sozinho.
Work item: SimbaValidador_JUDTASK0032589 | tentativa 1 | runner vm01-rpa
```

As etapas aparecem por extenso: download dos arquivos anexados à tarefa, cadastro e validação no Simba Validador, envio dos arquivos gerados para a tarefa, transmissão pelo Simba Transmissor, registro do comprovante na tarefa.

Se o JSON for inválido, a JUDTASK é localizada pelo número no nome do work item. Uma falha ao comentar só fica no log, porque o status do work item já foi gravado.

---

## 6. Correção automática dos GABs

### 6.1 Por que os arquivos são reprovados

Os GABs são **posicionais**: cada campo ocupa posições fixas, e a linha tem tamanho fixo. O Validador lê o arquivo na codificação padrão do Windows (**Windows-1252**) e corta os campos por posição. Leiautes, tirados do `simba-validador.jar`:

| Arquivo | Versão 1 (em uso) | Versão 2 |
|---|---|---|
| GAB109 (movimentação) | 127 posições | 333 |
| GAB112 (cadastro) | 307 posições | não suportada pela correção |
| GAB800 (saldos) | 298 posições | 320 |

Bateria de testes no Validador 5.8.7, com o mesmo arquivo válido e um defeito por vez:

| Defeito | Resultado no Simba |
|---|---|
| "ª", "º", "°", "Ç", "É" em **Windows-1252** | Aprovado |
| TAB ocupando 1 posição dentro de um campo | Aprovado |
| Quebra de linha LF em vez de CRLF | Aprovado |
| Acentos em **UTF-8** (cada um ocupa 2 bytes e desloca a linha) | **Reprovado**: "Certifique-se de completar com espaços..." ou erros de campo na linha deslocada |
| **BOM** UTF-8 no início | **Reprovado** (linha 1) |
| Linha **sem os espaços finais** | **Reprovado** |
| Linha com **espaços a mais** no fim | **Reprovado** |
| **Linha em branco** (inclusive no fim do arquivo) | **Reprovado** |

O caso conhecido do "ª" que precisava ser trocado por espaço é o arquivo em UTF-8. Trocar o "ª" por espaço resolvia porque tirava um byte da linha. A correção automática faz melhor: converte o arquivo para Windows-1252 e **mantém o "ª"** e os demais acentos.

### 6.2 Regras

Quando o Validador reprova um caso **Corretora (GAB)**, o RPA examina os GABs da pasta e aplica só correções mecânicas, que não alteram o conteúdo dos campos:

1. remove o BOM;
2. converte UTF-8 para Windows-1252, mantendo os caracteres. Um caractere sem equivalente vira 1 espaço, para manter as posições;
3. remove linhas em branco;
4. completa com espaços as linhas mais curtas que o leiaute;
5. remove espaços excedentes das linhas mais longas. Se o excesso tiver dados, o arquivo **não** é corrigido.

Depois **valida de novo uma vez**:
- **Aprovado:** segue o fluxo, e a JUDTASK recebe uma nota de auditoria com cada correção, por arquivo. As cópias corrigidas vão para a tarefa (em `arqtxt`); os anexos originais não são alterados.
- **Ainda reprovado:** falha de negócio, e o comentário inclui a lista das correções já feitas. Erros de dados (CPF inválido, investigado ausente, data) não são corrigidos: voltam para o usuário.

Se nada for corrigível, ou se um arquivo tiver dados além do leiaute, nenhum arquivo é alterado.

Limites: só GAB (tipo Corretora), porque o CC 3454 tem outro formato e ainda não foi testado. GAB112 só na versão 1 do leiaute.

---

## 7. Chaves do Transmissor

| Tema | Como funciona |
|---|---|
| O que é | Arquivo de chaves da instituição financeira, emitido para o Simba. O CNPJ e o Nº do Banco da chave precisam bater com os do atendimento. São 4 instituições (Banco XP, XP, Rico, Clear), portanto 4 chaves |
| Onde fica | Pasta `SIMBA_CHAVES_DIR`, uma pasta do servidor definida no `.env` de cada runner |
| Como o runner escolhe | Pelo campo `Chave` do work item: `SIMBA_CHAVES_DIR\<Chave>` |
| Senha | `.env`: `SIMBA_SENHA_<nome do arquivo sem extensão, maiúsculo, _ no lugar de espaços/símbolos>`. Ex.: `XP Corretora.chave` → `SIMBA_SENHA_XP_CORRETORA` |
| Uso | O runner digita a senha no diálogo do Transmissor. A senha nunca vai para log, comentário ou work item |
| Erros | Chave inexistente → "Arquivo não localizado."; senha com tamanho fora de 8 a 16 caracteres; chave inválida ou senha errada → "Arquivo de chaves inválido ou senha incorreta.". Todos viram falha com comentário |
| Atenção | O Transmissor grava autorizações do órgão **dentro** do arquivo de chaves. Recomendação: cada runner usa uma cópia local, distribuída a partir de uma mestre já autorizada (ver análise de produção, 4.3) |

---

## 8. Pastas e arquivos

Em cada runner, sob `Documentos\Programas SIMBA` (ou `SIMBA_HOME`):

| Pasta | Conteúdo | Ciclo de vida |
|---|---|---|
| `Validador\`, `Transmissor\` | Instalação do Simba (logs em `logs\`) | Fixa |
| `dadosValidador\<atendimento>\` | Base do Simba para o caso em andamento: cadastro, `arqtxt\`, `envio\`, relatório | Só durante o processamento; depois vai para `Arquivo\` |
| `Trabalho\<work item>\` | Downloads temporários do ServiceNow | Apagada ao fim de cada item |
| `Arquivo\<atendimento>\` (`SIMBA_ARQUIVO`) | Casos já processados, com sucesso ou falha. Se o mesmo caso voltar, ganha sufixo de data e hora | Permanente: **definir retenção** (dados sigilosos) |
| `Transmitidos\<atendimento>\` (`SIMBA_TRANSMITIDOS`) | Comprovante PDF + `<atendimento>_GABs.zip` | Permanente: definir retenção |
| `logs\runner.log` | Log do runner, rotativo (10 × 10 MB) | Rotativo |

Mover cada caso para `Arquivo\` mantém as listas do Validador e do Transmissor curtas, mesmo com milhares de casos. O teste com 30 casos seguidos termina com a lista igual à do início.

---

## 9. Segurança (resumo)

Detalhes e recomendações em [analise-producao.md](analise-producao.md), seção 2.

- **Credenciais:** usuário de integração do ServiceNow com menor privilégio. Senhas no `.env`, fora do git; restringir com ACL NTFS + BitLocker, ou usar um cofre.
- **Dados sigilosos:** GABs e comprovantes estão sob sigilo bancário (LC 105/2001) e contêm dados pessoais (LGPD). Ficam em `Arquivo\` e `Transmitidos\`: definir retenção e acesso. Não deixar `Programas SIMBA` dentro do OneDrive. Nesta máquina ele está, e o OneDrive já travou um arquivo durante uma validação.
- **Sessões:** os runners precisam de sessão Windows desbloqueada. Use VMs dedicadas, sem uso humano, em rede restrita.
- **Envio em duplicidade:** cinco defesas:
  1. item em envio nunca volta para a fila;
  2. etapa `enviando` gravada antes do clique;
  3. comprovante já registrado → não envia;
  4. Transmissor recusa atendimento já enviado;
  5. verificação de posse da reserva antes do Enviar.
- **Auditoria:** cada work item registra o runner (`remarks`), as etapas e o resultado. A JUDTASK guarda comentários, notas de correção e o comprovante.

## 10. Performance e escala

| Medida | Valor (medido nesta máquina) |
|---|---|
| Abertura do Simba | ~1,5s; picos de 15 a 60s (chamadas ao servidor do MPF) |
| Cadastro + validação + geração | ~5–8s por caso |
| Lote de 30 casos diferentes (com abertura do Simba, metade com correção automática) | 231s, **~7,7s por caso**; 2 etapas precisaram de 1 nova tentativa automática |
| Download/upload no ServiceNow | Não medido (depende do tamanho dos GABs) |
| Transmissão | Não medida (envio real ainda não executado) |

Escala: 1 runner = 1 sessão Windows = 1 caso por vez; para escalar, adicione runners.
- **Validador:** o Simba responde por ~8s por caso. Contando o ServiceNow, ~1 min por caso é uma estimativa conservadora: 5000 casos ≈ 83 h-runner (10 runners ≈ 8 h).
- **Transmissor:** depende do servidor do órgão e da autorização das chaves.
- **Carga no ServiceNow:** com 20 runners fica abaixo de 1 requisição/s fora os anexos.

## 11. Configuração (`python/.env`)

| Variável | Obrigatória | Uso |
|---|---|---|
| `SN_INSTANCIA`, `SN_USUARIO`, `SN_SENHA` | Runner | ServiceNow (usuário de integração) |
| `RUNNER_ID` | Não | Nome do runner nos work items (padrão: máquina-usuário) |
| `SIMBA_CHAVES_DIR` | Transmissor | Pasta dos arquivos de chaves |
| `SIMBA_SENHA_<CHAVE>` | Transmissor | Senha de cada arquivo de chaves |
| `SIMBA_HOME` | Não | Pasta `Programas SIMBA` (padrão: Documentos do usuário) |
| `SIMBA_ARQUIVO` | Não | Casos processados (padrão: `<SIMBA_HOME>\Arquivo`) |
| `SIMBA_TRANSMITIDOS` | Não | Pasta de cada caso transmitido (padrão: `<SIMBA_HOME>\Transmitidos`) |
| `SIMBA_TRABALHO` | Não | Downloads temporários (padrão: `<SIMBA_HOME>\Trabalho`) |
| `RC_JAVA_ACCESS_BRIDGE_DLL` | Não | Caminho da DLL do JAB |
| `SN_FILA_TESTE` | Testes | Fila de teste do `pytest -m servicenow` |

Parâmetros fixos em `config.py`: tempos de espera (abertura 60s, tela 20s, validação 5 min, envio 5 min), 3 tentativas por etapa e por item, lease de 15 min, heartbeat de 60s, reaper a cada 5 min.

## 12. Testes

| Comando (em `python\`) | O que cobre | Precisa de |
|---|---|---|
| `.venv\Scripts\python -m pytest` | Abertura, seletores, Passo 1, recuperação de queda, texto dos comentários, correção dos GABs (sem Simba), cálculo do DV, zip dos GABs | Simba Validador |
| `... -m cadastro` | Cadastro, validação, geração, fluxo completo, 6 defeitos de GAB corrigidos no Simba real, erro de dados que continua reprovando, Transmissor até a senha, lote de vários casos com arquivamento (`SIMBA_TESTE_CASOS=N`, padrão 10) | Simba Validador + Transmissor; cria casos fictícios locais |
| `... -m servicenow` | Reserva com 8 runners concorrentes, devolução, falha, reaper, anexos | Usuário de integração e fila de teste no DEV |

Os testes usam o Simba de verdade, sem simulação, e matam o Simba ao terminar. Os casos fictícios usam o destino `002-PF`, com números 013110 e 900001 em diante e DV calculado.

## 13. Limitações conhecidas

- O envio real (Enviar → comprovante) nunca foi executado: não há chave nesta máquina, e o envio vai para produção.
- A validação CC 3454 (tipo Banco) nunca foi testada, e a correção automática não cobre esse formato.
- Os runners ainda não rodaram contra o ServiceNow (falta usuário de integração e fila de teste no DEV).
- Lista completa e prioridades em [analise-producao.md](analise-producao.md).

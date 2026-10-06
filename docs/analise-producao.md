# Análise para produção — RPA Simba (Validador + Transmissor) com N runners

**Data:** 05/10/2026
**Escopo:** o que falta, segurança, escalabilidade, resiliência e riscos para colocar em produção o processamento de ~5000+ casos pelos runners Python (`python -m simba.runner`) consumindo as filas do RPA Hub no ServiceNow.
**Leitura de apoio:** [documentacao-completa.md](documentacao-completa.md), [estado-atual.md](estado-atual.md), [teste-em-outro-computador.md](teste-em-outro-computador.md), [Simba Transmissor.md](../Simba%20Transmissor.md).

## Resumo

- **Pronto e testado contra os apps reais:**
  - Validador completo (cadastro → validação GAB → geração do pacote, ~8s por caso num lote de 30);
  - correção automática dos defeitos de GAB conhecidos;
  - arquivamento de cada caso, para a lista do Simba não crescer;
  - Transmissor até a senha da chave;
  - recuperação automática de travamentos do Simba.
- **Escrito, mas nunca executado contra o ServiceNow:** runners, protocolo de reserva, reaper e comentários de erro na JUDTASK. Falta usuário de integração e fila de teste no DEV.
- **Nunca exercido:** o **envio real** (Enviar → comprovante) e a validação **CC 3454** (tipo Banco: ~490 tarefas no DEV).
- **Maiores riscos:**
  - envio em duplicidade ao órgão;
  - vazamento de dados sob sigilo bancário, hoje copiados em disco local, possivelmente sincronizado pelo OneDrive;
  - o arquivo de chaves ser alterado pelo próprio Transmissor (autorizações) e compartilhado entre runners;
  - atualizações obrigatórias do Simba parando todos os runners de uma vez.

---

## 1. O que falta (funcional)

| # | Item | Por que importa | Prioridade |
|---|---|---|---|
| F1 | **Envio real nunca executado.** Os caminhos do diálogo do comprovante vêm do `.iBot` e não foram conferidos; o texto exato de sucesso e o nome do PDF são desconhecidos | É a única etapa irreversível. Sem isso, o Transmissor não está pronto | Bloqueante |
| F2 | Validação **CC 3454** (tipo `Banco`) nunca testada | Banco XP é ~1/4 dos casos | Bloqueante para Banco |
| F3 | Runners nunca rodaram contra o SN (`pytest -m servicenow` e um item ponta a ponta) | O protocolo de reserva e o reaper só são confiáveis depois do teste de concorrência | Bloqueante |
| F4 | Confirmar com o time do SN: o fluxo reage só ao `status` do work item? Usa `response_content`/`robot`? O `request_content` do Validador em PROD traz o JSON completo? | Se o fluxo esperar algo que o runner não grava, as tarefas não andam | Bloqueante |
| F5 | **Desligar os robôs Intellibot** das filas Simba Validador/Transmissor antes do piloto | Os dois consumiriam a mesma fila; o Intellibot não respeita o token do runner | Bloqueante |
| F6 | Arquivos reais do SN nunca validados. Hoje o runner baixa **todos** os anexos da JUDTASK para a pasta de validação | Um anexo que não é GAB/CC (ofício, PDF) pode reprovar a validação. Pode ser preciso filtrar por nome | Alta |
| F7 | Autorização da chave por "computador" ([seção 4.3](#43-transmissor-e-chaves)) | Pode impedir runners de transmitir ou exigir um passo manual por chave | Alta |
| F8 | Início automático do runner no logon, watchdog e reinício após Windows Update | Hoje o runner só roda se alguém o iniciar | Alta |
| F9 | Conferência de integridade dos anexos baixados: hoje só o tamanho; o SN guarda um hash do anexo | Arquivo corrompido em trânsito | Média |
| F10 | Limite de tamanho de anexo da instância (propriedade `com.glide.attachment.max_size`) e timeout de upload para pacotes grandes | Casos grandes podem falhar sempre | Média |
| F11 | Fila "Execução de Garantias" (existe no SN) fora do escopo atual | Definir se entra no projeto | Definir |

---

## 2. Segurança

### 2.1 Credenciais

| Segredo | Onde está hoje | Risco | Recomendação |
|---|---|---|---|
| Usuário de integração do SN | `.env` em texto puro em cada runner (basic auth) | Quem lê o arquivo age no SN como o RPA | Usuário dedicado por ambiente, **menor privilégio** (só as 3 tabelas + comentários), senha forte e rotacionada. Migrar para OAuth client credentials quando o SN liberar |
| Senhas dos arquivos de chaves | `.env` (`SIMBA_SENHA_*`) | Chave + senha = transmitir em nome da instituição | No mínimo: ACL NTFS no `.env` só para a conta do runner e disco com BitLocker. Melhor: Windows Credential Manager/DPAPI, ou o `sensitive_content` do work item / cofre de credenciais do RPA Hub (`sn_rpa_fdn_external_credential_vault` existe na instância), como o `.iBot` fazia |
| Arquivos de chaves | Pasta do servidor (`SIMBA_CHAVES_DIR`) | Cópia indevida da chave | Pasta com acesso só das contas dos runners, auditoria de leitura, backup protegido |

O `.env` está no `.gitignore`; o `.env.example` não tem segredos.

### 2.2 Dados sob sigilo bancário e LGPD

Os GABs, o pacote de envio e o comprovante contêm dados bancários sob **sigilo (LC 105/2001)** e dados pessoais (CPF, nome).

| Onde ficam cópias no runner | Situação atual | Risco |
|---|---|---|
| `Trabalho\<work item>` (downloads) | Apagado ao fim de cada item, com sucesso ou erro | Baixo |
| `dadosValidador\<atendimento>` | Só durante o processamento; ao fim de cada caso (sucesso ou falha) é **movido** para `Arquivo\` | Baixo |
| `Arquivo\<atendimento>` (`SIMBA_ARQUIVO`) | Todos os casos processados **mantidos** (para as listas do Simba não crescerem e para análise de falhas) | Acúmulo de dados sigilosos: precisa de retenção e acesso restrito |
| `Transmitidos\<atendimento>` | Comprovante PDF + zip dos GABs **mantidos** (pedido do negócio) | Precisa de política de retenção e de acesso |
| `logs\runner.log` | Sem dados dos investigados, mas mensagens do Simba podem citar CPF (ex.: "<CPF> não foi encontrado no arquivo cadastral") | Baixo/médio |
| Comentário na JUDTASK | Inclui a mensagem do Simba (pode ter CPF) | Aceitável se a tarefa já é restrita; confirmar com o jurídico |

**Atenção — OneDrive:** nesta máquina a pasta Documentos é redirecionada para o OneDrive, então `Programas SIMBA\dadosValidador` **sincroniza para a nuvem**. Além do vazamento, o OneDrive já **travou um arquivo durante uma validação**: o Validador abortou com "Ocorreu um erro do sistema" (`O arquivo já está sendo usado por outro processo` em `arqtxt\`). Nos runners, a pasta `Documentos` não pode estar no OneDrive; se estiver, use `SIMBA_HOME` fora dele. Isso depende de onde o Simba grava, então confirme na instalação.

Recomendações:
- disco criptografado (BitLocker) nos runners;
- definir retenção e local de `Arquivo` e `Transmitidos` (pasta de rede com acesso restrito);
- registrar a análise com o DPO/jurídico.

### 2.3 Sessão interativa

O JAB exige desktop desbloqueado e logado. Uma sessão sempre aberta é uma superfície de ataque: quem chega ao console age como o runner.
- Runners em VMs dedicadas, numa rede restrita, sem uso humano e sem e-mail ou navegação.
- Acesso ao console só para operação.
- Desconectar o RDP bloqueia a sessão e quebra o JAB. Use sessão de console da VM, ou a política de "não bloquear ao desconectar" com controle compensatório.

### 2.4 Rede e software

- Tráfego HTTPS para o SN e para `simba.mpf.mp.br`. O Simba suporta proxy (`dadosValidador\conf\configuracoes`).
- Dependências Python com versão fixada em `requirements.txt`. O `java-access-bridge-wrapper` carrega uma DLL do Windows. Revisar antes de atualizar.
- Instalação nos runners a partir de uma tag/branch revisada, nunca código editado na máquina.

---

## 3. Escalabilidade e capacidade

### 3.1 Unidade de escala

**1 runner = 1 usuário Windows = 1 caso por vez.** O Simba usa as pastas do usuário e uma instância por sessão. Para escalar, adicione sessões.

| Topologia | Prós | Contras |
|---|---|---|
| N VMs, 1 sessão cada | Isolamento simples; uma VM ruim não afeta as outras | Custo de N VMs e N instalações do Simba |
| Servidor RDS com N usuários | Menos máquinas | Cada usuário precisa do Simba configurado e do JAB ligado. Memória: o Validador usa até ~1,8 GB de heap e o Transmissor até ~7 GB (padrão da JVM nesta máquina); limitar com `-Xmx` se necessário. Uma falha do servidor derruba todos |

### 3.2 Throughput (estimativa a medir no piloto)

| Etapa | Tempo |
|---|---|
| Validador no Simba | ~4–5s (medido com caso fictício) |
| Abertura do Simba | ~1,5s, com picos de 15–30s+ (medido) |
| Download/upload de anexos | Depende do tamanho; não medido |
| Transmissão ao órgão | Não medido (timeout configurado: 5 min) |

Com ~1 min por caso somando tudo, **5000 casos ≈ 83 h-runner**: ~8 h com 10 runners, ~4 h com 20. O gargalo provável é a transmissão (rede e servidor do órgão), não o Simba.

### 3.3 Carga no ServiceNow

Por runner: 1 listagem por fila a cada 30s quando ocioso, 3 chamadas por reserva, 1 PATCH de heartbeat por minuto, mais downloads e uploads. Com 20 runners, bem abaixo de 1 requisição/s fora os anexos. Pontos de atenção:
- todos os runners usam o mesmo usuário de integração: verificar limite de transações concorrentes por usuário (semáforo da instância);
- o upload e o download dos anexos é o que pesa: dimensionar banda.

### 3.4 Limites do protocolo de reserva

- A reserva sorteia entre os 20 itens mais antigos. Com mais de ~20 runners as colisões aumentam (só custam tempo, não duplicam). Aumentar a janela se for preciso.
- Cada reserva espera 2s para confirmar; aceitável perto de ~1 min por caso.
- O reaper roda em todos os runners a cada 5 min. É redundante, mas idempotente.

### 3.5 Limites externos

- **Servidor do órgão:** sem informação sobre limite de envios. Começar com poucos runners de Transmissor e aumentar.
- **Chaves:** ver 4.3. Se a autorização for por máquina, só as máquinas autorizadas transmitem, e a escala do Transmissor fica limitada a elas.

---

## 4. Resiliência: o que acontece quando algo falha

| Falha | Comportamento atual | Risco residual |
|---|---|---|
| Simba trava ou cai no meio de uma etapa | `run_step` mata, reabre e repete a etapa (até 3x). Depois, o item volta para a fila com espera de 5 min × tentativa, até 3 tentativas; então falha definitiva + **comentário na JUDTASK** | Baixo |
| Erro de negócio (DV inválido, arquivos reprovados, JSON incompleto) | Falha `business` na hora, sem nova tentativa, com **comentário na JUDTASK** dizendo onde parou e o que corrigir | Baixo |
| Processo do runner morre / máquina reinicia | O item fica `in_progress` sem heartbeat. Após 15 min, o reaper de outro runner devolve o item (ou falha, se esgotou as tentativas) e **comenta na JUDTASK** | Atraso de até ~20 min. Sem autostart (F8), a máquina para de contribuir |
| ServiceNow indisponível | Cada chamada tenta 3x com espera; o runner continua no loop. Itens em andamento podem ser recolhidos pelo reaper; o dono percebe na próxima etapa e para | Se o SN cair durante o registro do comprovante, o item vira "verificar manualmente" |
| Falha ao gravar o comentário | Só log; o status do work item já foi gravado | O usuário vê a falha no work item, mas não na tarefa |
| Falha depois do Enviar | `TransmissaoIncerta` / etapa `enviando` ou `registrando` → falha `application` "verificar manualmente". **Nunca volta para a fila** | Exige tratamento manual (comprovante fica em `Transmitidos`) |

### 4.1 Envio em duplicidade (risco mais grave)

Defesas existentes:
1. o item do Transmissor nunca volta para a fila depois de `enviando`;
2. antes de enviar, o runner pula a tarefa que já tem `evidence_attachment`;
3. o Transmissor recusa atendimento "já enviado anteriormente".

Brechas que continuam:
- **Corrida residual na reserva:** dois runners gravam a reserva com mais de 2s de diferença depois de ambos lerem o item como pendente. É improvável, mas possível. Para fechar: Business Rule no SN que rejeita `in_progress → in_progress` com outro token.
- **Item novo para a mesma JUDTASK** (usuário reenvia) quando o envio anterior aconteceu mas o comprovante não foi registrado (falha no registro). A defesa 2 não pega esse caso. A defesa 3 só vale na mesma máquina, porque o runner é sem estado. Orientar o usuário (o comentário já diz "verificar manualmente") e, se possível, consultar o órgão.

### 4.2 Atualização obrigatória do Simba

Validador e Transmissor consultam a versão no servidor ao abrir. Se houver versão nova obrigatória ("A versão deste sistema não é atual... Favor desinstalar esta versão e instalar a mais nova"), **todos os runners param ao mesmo tempo**. O Transmissor também recusa atendimentos validados com versão antiga. Isso exige:
- alerta quando aparecer essa mensagem;
- procedimento de atualização em todos os runners juntos;
- rodar a suíte de testes de seletores (`pytest`) depois de atualizar, porque a tela pode mudar.

### 4.3 Transmissor e chaves

Encontrado no `simba-transmissor.jar` / `spea-client.jar`:
- o Transmissor verifica se a chave está **autorizada "no computador"** ("Este arquivo de chaves não está autorizado no computador em uso", botão "Solicitar Autorização...");
- a autorização é pedida ao órgão e **gravada dentro do arquivo de chaves**.

Consequências:
- Se "computador" for a máquina local, cada runner precisa de autorização por chave. Se for o órgão de destino (mais provável, pelo texto "autorizado para esse Órgão"), a autorização vale para todos. **Confirmar com um teste real.**
- O app **escreve no arquivo de chaves**. N runners usando o mesmo arquivo numa pasta compartilhada podem corromper ou sobrescrever autorizações. Recomendação: cada runner usa uma cópia local, distribuída a partir de uma versão "mestre" já autorizada; a pasta compartilhada fica só para leitura.
- O CNPJ e o Nº do Banco do atendimento precisam bater com a chave: **4 instituições = 4 chaves**, cada uma com senha.

---

## 5. Operação e observabilidade

| Tema | Hoje | Falta |
|---|---|---|
| Painel | Lista de work items no SN por status/`exception_type`; comentários na JUDTASK | Relatório/dashboard no SN: itens por status, falhas por tipo, tempo por item |
| Logs | Arquivo rotativo por runner (`Programas SIMBA\logs\runner.log`) | Centralizar (SIEM ou similar) para investigar sem acessar cada VM |
| Saúde dos runners | Nenhuma | Registro de runners vivos (último heartbeat por `RUNNER_ID`) e alerta quando um some |
| Alertas | Nenhum | Falhas `application` acima do normal; itens `in_progress` antigos; mensagem de versão desatualizada do Simba |
| Implantação | Manual (`git` + `pip`) | Script de instalação/atualização para N runners, com versão fixada |
| Tratamento manual | Comentário na JUDTASK com etapa, erro e orientação | Runbook para o time: o que fazer em cada tipo de comentário, principalmente "verificar transmissão manualmente" |

---

## 6. Matriz de riscos

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Envio em duplicidade ao órgão | Baixa | Muito alto | 4.1; Business Rule no SN; runbook |
| Dados sigilosos em disco/OneDrive dos runners | Média | Muito alto | 2.2; BitLocker; `SIMBA_HOME` fora do OneDrive; limpeza em falha |
| Vazamento de chave + senha | Baixa | Muito alto | 2.1; cofre de credenciais; ACL; auditoria |
| Atualização obrigatória do Simba para todos os runners | Média | Alto | 4.2; alerta; procedimento de atualização |
| Mudança de tela do Simba quebra seletores | Média | Alto | `pytest` após cada atualização; fallback por rótulo (`Control.label`) |
| Arquivo de chaves alterado concorrentemente | Média | Alto | 4.3; cópia local por runner |
| Fluxo do SN não reage como esperado ao status | Média | Alto | F4; piloto no DEV |
| Robôs Intellibot e runners na mesma fila | Média | Alto | F5 |
| Anexos que não são GAB/CC reprovam a validação | Média | Médio | F6; filtro por nome |
| Correção automática altera um arquivo indevidamente | Baixa | Alto | Só correções mecânicas (codificação, BOM, linhas em branco, espaços de preenchimento), testadas no Simba real; nova validação obrigatória; nota de auditoria na JUDTASK; anexos originais intactos |
| Lista suspensa do Simba cresce com milhares de casos | Alta sem mitigação | Alto | Cada caso é movido para `Arquivo\` ao terminar; teste com 30 casos seguidos sem crescimento da lista |
| Sessão bloqueada/desconectada para o JAB | Alta | Médio | 2.3; VMs dedicadas; autostart (F8) |
| Abertura lenta do Simba (15–30s+) | Alta | Baixo | `STARTUP_TIMEOUT` = 60s; retry |
| Servidor do órgão limita ou recusa volume | Desconhecida | Alto | Rampa gradual de runners de Transmissor |
| Corrida residual na reserva (Validador) | Baixa | Baixo | Reprocessar o Validador é seguro (re-cadastro sobrescreve; anexos sem duplicar) |

---

## 7. Checklist antes de produção

- [ ] `pytest -m servicenow` verde no DEV (inclui 8 runners concorrentes)
- [ ] Ponta a ponta no DEV: Validador → Transmissor até a senha, com comentários de erro conferidos na JUDTASK
- [ ] Um envio real controlado (caso real autorizado), conferindo comprovante, `evidence_attachment` e o comportamento do fluxo do SN
- [ ] CC 3454 validado com arquivos reais
- [ ] Respostas do time do SN (F4) e Intellibot desligado nas filas (F5)
- [ ] Usuário de integração com menor privilégio; segredos fora de texto puro (ou `.env` com ACL + BitLocker)
- [ ] Runners com `SIMBA_HOME` fora do OneDrive, disco criptografado, sessão que não bloqueia
- [ ] Chaves: autorização confirmada e estratégia de cópia local
- [ ] Autostart/watchdog do runner e alertas básicos
- [ ] Runbook do tratamento manual entregue ao time
- [ ] Piloto com poucos casos reais e poucos runners, comparando com o processo atual; depois, rampa

## 8. Perguntas em aberto

1. O fluxo do SN usa algo além do `status` do work item (por exemplo `response_content`)?
2. O `request_content` dos itens do Validador em PROD traz o JSON completo do caso?
3. A autorização da chave é por máquina ou por órgão? O órgão tem ambiente de teste (o Transmissor tem um rótulo oculto "Ambiente de testes")?
4. Existe limite de envios por período no servidor do órgão?
5. Qual a retenção exigida para comprovantes e para o zip dos GABs, e onde eles devem ficar?
6. Os comentários na JUDTASK podem conter as mensagens do Simba com CPF?

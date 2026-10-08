> **Documento histórico** (planejamento da migração). O estado atual está em [solucao.md](solucao.md) e a operação na VM em [operacao-vm.md](operacao-vm.md).

# Plano de Implantação — RPA Simba (Validador + Transmissor) com N runners

**Atualizado em:** 05/10/2026 (versão original: 03/10/2026)
**Código:** branch `runners-servicenow` em https://github.com/tiigortadeu/RPASIMBA
**Leitura de apoio:**
- [documentacao-completa.md](documentacao-completa.md): como o sistema funciona;
- [analise-producao.md](analise-producao.md): o que falta, riscos e checklist; os códigos F1–F12 deste plano vêm de lá;
- [teste-em-outro-computador.md](teste-em-outro-computador.md): instalação e testes numa máquina nova.

## Objetivo

Processar ~5000+ ofícios judiciais de afastamento de sigilo bancário no Simba sem intervenção humana, com várias máquinas em paralelo. Para cada caso:
1. pegar o caso na fila do ServiceNow;
2. baixar os GABs;
3. cadastrar, validar (corrigindo automaticamente os defeitos conhecidos) e gerar o pacote no **Simba Validador**;
4. transmitir pelo **Simba Transmissor**;
5. devolver o resultado ao ServiceNow;
6. em qualquer erro, registrar na JUDTASK onde parou, por quê e o que o usuário deve fazer.

## Decisões tomadas

| Tema | Decisão |
|---|---|
| Fonte do trabalho | **Filas do RPA Hub já existentes** no ServiceNow ("Simba Validador", "Simba Transmissor"). O fluxo do SN que cria os itens e encaminha Validador → Transmissor continua igual; os runners Python substituem os robôs Intellibot |
| Acesso ao ServiceNow | REST direto (Table API + Attachment API), sem MCP |
| Autenticação | Usuário de integração com basic auth (OAuth client credentials se o time do SN liberar) |
| Execução | N runners sem estado, 1 por sessão Windows, 1 caso por vez (`python -m simba.runner`) |
| Reserva de itens | Pelo status do work item (`pending` → `in_progress`) com token e conferência (`simba/fila.py`) |
| Arquivos a validar | Anexos da JUDTASK do Validador, baixados pela API |
| Chaves do Transmissor | Arquivos numa pasta do servidor (`SIMBA_CHAVES_DIR`); senhas no `.env` de cada runner |
| Erros | Toda parada vira status no work item + comentário na JUDTASK; retries automáticos só em nota de trabalho |
| Correção automática | Só defeitos mecânicos dos GABs (UTF-8, BOM, linhas em branco, espaços de preenchimento), com nova validação e nota de auditoria |
| Saída do Transmissor | Uma pasta por caso em `Transmitidos\<caso>\` com o comprovante PDF e o `<caso>_GABs.zip` |
| Lista do Simba | Cada caso processado sai do `dadosValidador` para `Arquivo\` (sucesso ou falha) |

```
ServiceNow (filas + JUDTASK + anexos)
   ▲ REST
runner 1 … runner N   (Windows + Simba + JAB, 1 caso por vez)
   reservar → baixar → Validador (cadastro, validação, correção, geração) → anexar → concluir
   reservar → baixar pacote → Transmissor (chave, senha, envio) → comprovante → concluir
   erro em qualquer ponto → status no work item + comentário na JUDTASK
```

---

## Situação por fase

Legenda: ✅ feito e testado · 🟡 feito, falta testar no ambiente real · ⬜ a fazer

### Fase 0 — Ambiente (máquina de teste / PC do trabalho)

| # | Atividade | Situação |
|---|---|---|
| 0.1 | Python 3.11, venv, `requirements.txt` | ✅ nesta máquina · ⬜ PC do trabalho |
| 0.2 | Java Access Bridge ligado (`jabswitch -enable`) | ✅ nesta máquina · ⬜ PC do trabalho |
| 0.3 | `pytest` (36 testes) e `pytest -m cadastro` (23 testes) verdes | ✅ nesta máquina · ⬜ PC do trabalho |
| 0.4 | `Programas SIMBA` fora do OneDrive (`SIMBA_HOME`) | ⬜. O OneDrive já travou um arquivo do Simba durante uma validação |

Como fazer: [teste-em-outro-computador.md](teste-em-outro-computador.md).

### Fase 1 — Simba Validador

| # | Atividade | Situação |
|---|---|---|
| 1.1 | Cadastro (Passo 1, Dados do Caso, investigados, Gravar) | ✅ |
| 1.2 | Validação GAB (Corretora) | ✅ com arquivos fictícios |
| 1.3 | Geração do pacote e conferência do hash | ✅ |
| 1.4 | Recuperação automática de travamentos e quedas do Simba | ✅ |
| 1.5 | Correção automática dos GABs | ✅ 6 defeitos testados no Simba real |
| 1.6 | Arquivamento de cada caso (lista do Simba não cresce) | ✅ lote de 30 casos |
| 1.7 | **Validação CC 3454** (tipo Banco, ~1/4 dos casos) | ⬜ nunca testada; precisa de arquivos de exemplo (F2) |
| 1.8 | Validação com **GABs reais** vindos do SN; filtrar anexos que não são GAB (F6) | ⬜ |

### Fase 2 — Simba Transmissor

| # | Atividade | Situação |
|---|---|---|
| 2.1 | Telas mapeadas, seleção do atendimento, chave + senha, erros de chave/senha | ✅ até a senha |
| 2.2 | Proteções contra envio em duplicidade | ✅ no código |
| 2.3 | Pasta do caso com comprovante + zip dos GABs | 🟡 o zip está testado; o comprovante depende do envio real |
| 2.4 | **Envio real controlado**: conferir o diálogo do comprovante, a mensagem de sucesso e o nome do PDF (F1) | ⬜ precisa de chave real e de um caso real autorizado |
| 2.5 | Autorização da chave: por máquina ou por órgão? Estratégia de cópia local por runner (F7) | ⬜ |

### Fase 3 — ServiceNow e runners

| # | Atividade | Situação |
|---|---|---|
| 3.0 | **Primeiro teste integrado no DEV** (JUDTASK0172345, 06/10/2026): usuário de integração autenticou; runner baixou os GABs, cadastrou, validou, gerou o pacote e anexou 9 arquivos na tarefa em 9,4s | ✅ fluxo · ⬜ status do work item (ver 3.3a) |
| 3.1 | Cliente REST, reserva, heartbeat, reaper, conclusão/falha | 🟡 testado no DEV até a gravação do status; testes `pytest -m servicenow` não executados (F3) |
| 3.2 | Comentários de erro e notas na JUDTASK | 🟡 texto testado; gravação no SN não testada |
| 3.3 | Usuário de integração no DEV e fila de teste "Simba Runner Teste" | 🟡 usuário existe e autentica · ⬜ fila de teste |
| 3.3a | **Dar o papel `sn_rpa_fdn.rpa_robot` ao usuário de integração** (sem ele o SN ignora a gravação do status do work item) e repetir o teste da JUDTASK0172345 (F13) | ✅ papel dado; item concluído com `success` |
| 3.3b | Transmissão direta no item do Validador (sem esperar a tarefa/fila do Transmissor), chave escolhida pelo CNPJ do caso (`SIMBA_CHAVE_<CNPJ>`) | 🟡 testada no DEV até a chave (sem chave nesta máquina): falha registrada e comentada na JUDTASK |
| 3.3c | **Retry do ServiceNow ao falhar:** ele recria o work item na hora; falhas permanentes viram loop (F14) | ⬜ **bloqueante**: definir regra com o time do SN ou limitar no runner |
| 3.4 | Respostas do time do SN: o fluxo usa só o `status`? O `request_content` do Validador traz o JSON? (F4) | ⬜ |
| 3.5 | **Regra de escolha dos itens da fila**: hoje é do mais antigo para o mais novo, sem critério (F12) | ⬜ definir com o negócio e implantar em `fila.reservar` |
| 3.6 | Ponta a ponta no DEV: JUDTASK de teste com GABs → Validador → Transmissor até a senha | ⬜ |
| 3.7 | Desligar os robôs Intellibot das filas antes do piloto (F5) | ⬜ |

### Fase 4 — Operação

| # | Atividade | Situação |
|---|---|---|
| 4.1 | Início automático do runner no logon + watchdog + reinício após Windows Update (F8) | ⬜ |
| 4.2 | Logs centralizados e alertas (falhas `application`, itens presos, versão do Simba desatualizada) | ⬜ |
| 4.3 | Runbook para o time: como tratar cada tipo de comentário, principalmente "verificar transmissão manualmente" | ⬜ |
| 4.4 | Procedimento de atualização do Simba em todos os runners | ⬜ |
| 4.5 | Retenção e acesso de `Arquivo\` e `Transmitidos\` (dados sigilosos, LGPD) | ⬜ |
| 4.6 | Segredos fora de texto puro (ou `.env` com ACL + BitLocker) | ⬜ |

### Fase 5 — Piloto e corte

| # | Atividade |
|---|---|
| 5.1 | Piloto com poucos casos reais e 1–2 runners, conferindo cada resultado |
| 5.2 | Comparar com o processo atual: tempo por caso, taxa de sucesso, correções automáticas, reprocessamentos |
| 5.3 | Rampa de runners (começar devagar no Transmissor por causa do servidor do órgão) |
| 5.4 | Desligar definitivamente os `.iBot` |

---

## Ordem sugerida

1. **Agora (sem dependências externas):** Fase 0 no PC do trabalho, seguindo o guia de teste.
2. **Em paralelo, com outras equipes:**
   - **Time do ServiceNow:** usuário de integração, fila de teste, respostas da 3.4, regra de prioridade (3.5).
   - **Negócio/jurídico:** caso real autorizado para o envio controlado, retenção dos arquivos e regra de prioridade.
   - **Instituições:** chaves e senhas.
3. Fase 3 no DEV (3.1 → 3.6), começando por `pytest -m servicenow`.
4. CC 3454 e GABs reais (1.7, 1.8).
5. Envio real controlado (2.4, 2.5).
6. Fase 4 e checklist da [análise de produção](analise-producao.md#7-checklist-antes-de-produção).
7. Piloto (Fase 5).

## Dependências e responsáveis

| Item | Depende de |
|---|---|
| **Papel `sn_rpa_fdn.rpa_robot`** no usuário de integração, fila de teste, desligar Intellibot, dúvidas do fluxo | Time do ServiceNow |
| Regra de prioridade dos itens | Negócio + time do ServiceNow |
| Chaves e senhas das 4 instituições; autorização das chaves | Responsáveis pelo Simba em cada instituição |
| Caso real para o envio controlado; retenção de dados | Negócio / jurídico / DPO |
| VMs ou sessões dos runners | Infraestrutura |
| Arquivos de exemplo CC 3454 | Operação (Banco XP) |

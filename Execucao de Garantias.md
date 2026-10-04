# Execução de Garantias — Resumo do Fluxo RPA

**Arquivo fonte:** `Execucao de Garantias.iBot`
**Formato:** WinAutomation / Automation Anywhere (Softomotive) — XML `AutxProcess`

## Informações gerais

| Campo | Valor |
|---|---|
| Nome do processo | Execucao de Garantias |
| Criado por | DESKTOP-IJE6HRV\Windows |
| Criado em | 2026-03-24 19:49:40 -03:00 |
| Atividade inicial | `Main` |

## Plugins referenciados

- Internet Explorer (9.0)
- Essential Toolkit (13.0)
- Universal App Connector (9.0)
- Essential Connectors (13.0)

## Fluxo (atividade "Main")

1. **EntryPoint** — início do processo.
2. **StartApp** — abre o atalho `C:\Users\Public\Desktop\Microsoft Edge.lnk` (Microsoft Edge), aguardando até 30s pela inicialização.
3. **ExitPoint** — fim do processo.

## Status

Fluxo no estágio inicial: apenas abre o Microsoft Edge. Nenhuma ação adicional (navegação, extração de dados, preenchimento de formulário, etc.) foi configurada ainda, apesar dos plugins presentes sugerirem automação de aplicação/web.

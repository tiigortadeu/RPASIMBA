# RPA Simba

Automação da resposta às requisições judiciais do CCS enviadas pelo **Simba**: cadastro e validação no Simba Validador,
transmissão ao órgão pelo Simba Transmissor e registro no ServiceNow, com um console de controle (dashboard, lista do
Bacen x ServiceNow, seleção e execução de lotes).

| Documento | Conteúdo |
|---|---|
| [docs/solucao.md](docs/solucao.md) | arquitetura, fluxo de um caso, componentes, erros, decisões |
| [docs/operacao-vm.md](docs/operacao-vm.md) | pontos de atenção, instalação na VM, operação diária, problemas comuns |
| [python/CLAUDE.md](python/CLAUDE.md) | guia técnico do código (comandos, testes, arquitetura) |

Código em [`python/`](python/). Configuração da máquina no `python/.env` (modelo em `python/.env.example`; nunca versionar o `.env`).

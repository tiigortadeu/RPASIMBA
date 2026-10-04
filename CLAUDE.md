# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

RPA process definitions exported from WinAutomation / Automation Anywhere (Softomotive) as `.iBot` files — XML documents with root `<AutxProcess xsi:type="AutxRpaProcess">` — plus a Python POC (`python/`) that is migrating the Simba Validador automation away from WinAutomation. Documentation and user-facing strings are in Portuguese.

- `Execucao de Garantias.iBot` — the target process being built. Currently only `EntryPoint -> StartApp (Microsoft Edge shortcut) -> ExitPoint`. Summarized in `Execucao de Garantias.md`.
- `Simba Validador.iBot` — a larger, complete reference process (~1 MB) with 9 activities: `Main`, `Passo 1`, `Passo 2`, `Passo 3`, `Dados do Caso`, `Adicionar Investigado`, `Downloads`, `Uploads`, `errorHandling`. `Main` pulls work items from the queue `Simba Validador` (`GetWorkItems` -> `ForEachLoop` -> `PickWorkItem`), drives the app via Universal App Connector, and dispatches to the other activities.
- Each `.iBot` has a companion `<name>.md` summary (Portuguese); `Simba Validador.md` is the most complete template (Informações gerais, Plugins, Variáveis, Dados de entrada, Telas, Fluxo per activity, Pontos de atenção).
- `docs/estado-atual.md` (what the POC does and what is validated) and `docs/plano-implantacao.md` (roadmap: ServiceNow REST/OAuth integration, Simba Transmissor, orchestrator).
- `trace.py` — parses `Simba Validador.iBot` and prints the control-flow tree of each activity; `trace_output.txt` is its saved output.

## Commands

```
python trace.py > trace_output.txt
```

The input filename is hardcoded in `trace.py` (`ET.parse(r"Simba Validador.iBot")`); edit it to trace another `.iBot`. Run from the project directory.

Python POC — run from `python/`, always with the project venv (the `python` on PATH is another tool's venv):

```
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest                      # opens/kills the real Simba app; skips `cadastro`
.venv\Scripts\python -m pytest tests/test_recovery.py -k queda
.venv\Scripts\python -m pytest -m cadastro          # grava the fictitious case tests/data/caso_teste.json (002-PF-013110-03) in local dadosValidador
.venv\Scripts\python scripts\dump_tree.py "Passo 1" # dump JAB tree of open Java windows with .iBot-style paths
.venv\Scripts\python -m simba.ui                    # desktop app (PySide6): connect to ServiceNow
```

Tests drive the real installed app (no mocks) and kill any running Simba instance. The `cadastro` marker (excluded by default in `pytest.ini`; run only with authorization) covers `test_cadastro.py`, `test_validacao.py` and `test_fluxo.py` — all of them create local atendimentos. The session-scoped `simba` fixture restarts the app once and kills it at the end; the terminal summary prints per-step timings and retry counts from `SimbaApp.timings`. `ERROR ... Failed to enumerate window` log lines come from JABWrapper probing non-Java windows and are harmless.

## Python POC architecture (`python/simba/`)

- The Simba Validador is a Java Swing app (`...\Documentos\Programas SIMBA\Validador\simba-validador.exe` → `javaw -jar simba-validador.jar`). It is automated through the **Java Access Bridge** (`java-access-bridge-wrapper`, DLL `C:\Windows\System32\WindowsAccessBridge-64.dll`). The `.iBot` UI selectors (`root pane[0].layered pane[1]...`) are JAB child-index paths and are reused verbatim in `screens.py`.
- `jab.py` — `Bridge` singleton runs the JAB message pump in a daemon thread; JVM/window discovery is asynchronous (~0.2s). `Element.by_path` walks child indexes and checks roles; `wait_for` polls (`config.POLL_INTERVAL`) instead of fixed sleeps. Only **visible** windows count: at startup `Passo 1` exists hidden behind a `Validador Bancário` splash.
- `app.py` — `SimbaApp` identifies Simba processes (launcher + `javaw` with `simba-validador.jar`), `control()` resolves by path and falls back to role+name when `Control.label` is set. `run_step()` is the robustness core: ensures app is at Passo 1, runs the step, fails on unexpected visible windows, and on recoverable errors kills the app and retries the whole step from Passo 1. `AppNotRunning` makes a crash fail fast instead of waiting for timeouts.
- `navigation.py` — Passo 1 helpers. App quirks: the Computador destino list loads ~0.6s after Passo 1 appears; Número do Caso is a 6-digit masked field and DV is 2 chars (reads are space-padded); combo selection uses JAB accessible selection by item index.
- `cadastro.py` — `Caso`/`Investigado` built from the same work-item JSON keys as the `.iBot` (`Caso.from_json`); `preencher_caso` (Passo 1 → Dados do Caso → investigados, verified via the investigados table) and `gravar` (Gravar → "Confirma gravação?" Sim → Informação OK). Saves to `dadosValidador/<Destino>-<Caso>-<DV>/`. Re-cadastrar an existing case opens an empty form and re-gravar overwrites (no duplicate), so retries are safe.
- **Clicks:** JAB action names are localized (`clicar`). Use `Element.press()` (request focus → wait for `focused` → post VK_SPACE) for any button that opens a modal dialog — `click()` (JAB action) blocks ~8s until the modal closes and JAB can't read the dialog meanwhile. Tabs have no actions; select them via the `page tab list` (`select_child`).
- **Business errors:** Simba validation dialogs titled `Aviso`/`Erro` become `SimbaAviso(message)` (`app.check_aviso`, `app.expect`, `app.expect_closed`); `run_step` does not retry them (restart won't fix bad data). Known: invalid DV; Número do Processo > 20 chars (CNJ number must be digits only).
- `validacao.py` — Passo 2: selects the atendimento, opens validation by work-item `Tipo` (`Banco` → CC 3454, `Corretora` → GAB), sets the folder in the `Selecione diretório para validação` file chooser, then waits for "Fim da verificação." in Mensagens. Approved = Continuar enabled and no known error phrase; rejected → presses << Voltar (back to Passo 1) and raises `ArquivosReprovados` (no retry). Expected files: GAB → `<atendimento>_GAB109/_GAB112/_GAB800.txt`; CC 3454 → `<atendimento>_AGENCIAS.txt`, etc.
- GAB112 (dados cadastrais) is positional, 307 chars/line; layout taken from enum `CamposGab112` in `simba-validador.jar` (see `tests/gab_ficticio.py`). GAB109/GAB800 may be empty. Every investigado with relacionamento must appear in GAB112 and vice versa. The validator's rules/messages live in `br/mp/mpf/spea/simba/validador/{enums,rules,carga}` inside the jar — read the class constant pools when a layout question comes up.
- `geracao.py` — Passo 3: Continuar >> → Gerar (≈0.3s, no dialog) → reads "hash\t<md5>" label and checks it against the MD5 of `dadosValidador/<atendimento>/envio/<atendimento>.zip`. Simba drops leading zeros from the MD5 (screen and `.zip.hash` alike), so compare numerically. **Fechar exits the whole Simba process**; `run_step` skips post-checks when the app is gone and the next step's `ensure_ready` restarts it.
- `fluxo.processar(app, caso, pasta)` — whole flow in two `run_step`s: `cadastro` (preencher + gravar) and `validar_e_gerar` (Passo 2 + Passo 3 + Fechar; kept together because Passo 3 only opens from an approved Passo 2). `Caso.tipo` comes from the JSON `Tipo`. Per user decision, the `.iBot`'s MoveDirectory to "Para transmitir", queue and ServiceNow parts are out of scope.
- Passo 2 and Passo 3 windows have an empty title; `Screen.marker` (a label checked by path) tells them apart.
- `.iBot` paths use `indexInParent`, not child position — they differ for tab content panels (`Element._child_by_index` handles both).
- `servicenow.py` — REST client (`requests`, no MCP). Two auth modes: browser session (cookies + `g_ck` as `X-UserToken`, needed because PROD uses SSO) and basic auth. `simba/ui/sso.py` does the SSO login in an embedded QtWebEngine window with an off-the-record profile and only accepts once `/api/now/ui/user/current_user` returns a non-guest user (the login page's `g_ck` belongs to the guest session).
- `config.py` resolves the real Documents folder (OneDrive-redirected), overridable with `SIMBA_HOME`. The `.iBot` hardcodes `C:\Users\<user>\Documents`, which is wrong on this machine.

## .iBot XML structure (needed to read flows)

- `<References>` lists plugin dependencies (`AutxPluginReference`: Essential Toolkit, Universal App Connector, Essential Connectors, Internet Explorer). The two files use different plugin versions.
- `<Activities>/<AutxActivity>` — each activity is a sub-flow with `ID`, `Name`, and `<Items>` of `<DesignItem xsi:type="...">`.
- Node types: `EntryPoint`, `ExitPoint`, `AutxMethod` / `AutxStaticMethod` (action calls, labeled by `<Name>`), `Decision` (ports `ControlYes`/`ControlNo`), `Switch` (`Options/SwitchOption`, each with its own `Port` and a `DataPort/StaticValue` case label), `ForEachLoop`, `StringFormat`, `StringComparer`, `ScriptTransform`, `AutxVariableContainer`, `ExecutionPoint` (invokes another activity), `Terminate2`.
- Edges are separate `DesignItem`s: `AutxControlConnection` (execution order) and `AutxDataConnection` (data wiring), referencing `SourceComponentID`/`SourcePortID` -> `SinkComponentID`/`SinkPortID`. To resolve a branch label, map the source port ID back to the owning node's named port (`ControlOut`, `ControlYes`, `ControlNo`, `ElsePort`, switch case port).
- Variables are declared as `AutxVariable` objects; the work queue is an `AutxObject` with `<QueueName>`.
- Files use CRLF line endings. When editing `.iBot` XML by hand, preserve IDs/GUIDs and port references exactly — the designer relies on them.

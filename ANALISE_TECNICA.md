# Análise Técnica e Plano de Profissionalização — HUB RPA

> Data: 02/09/2026 · Escopo: 38 arquivos Python (~2.700 LOC), frontend, scripts, testes e configuração.

## 1. Visão geral

| Arquivo | Linhas | Observação |
|---|---|---|
| `apps/api/rpa_hub_api/main.py` | 653 | God file: 36 rotas + lógica de negócio + mappers + orquestração |
| `apps/api/rpa_hub_api/schemas.py` | 206 | 26 modelos Pydantic |
| `apps/web/src/index.html` | 1.113 | SPA single-file (CSS/JS inline, sem build, servida do disco a cada request) |
| `rpa_core/engine/executor.py` | 326 | `_execute_step` sozinho ocupa ~190 linhas (87–276) |
| `rpa_core/engine/models.py` | 81 | `WorkflowStep` kitchen-sink: 26 campos opcionais |
| `infra/db/models.py` | 181 | 9 tabelas, constraints e índices decentes |
| `infra/db/session.py` | 28 | `create_all`, sem migrations |
| `infra/scheduler/service.py` | 67 | APScheduler em processo |
| `domain/secrets.py` | 47 | "Criptografia" XOR |
| `apps/worker/local_worker.py` | 37 | Só heartbeat, nunca pega jobs |
| `tests/` (3 arquivos) | 428 | 16 testes, sem `conftest.py` |

Ausências relevantes: 0 middlewares, 0 dependências de autenticação, 0 handlers globais de exceção, 0 endpoints de health, `structlog` declarado e nunca usado, sem CI, sem Alembic, sem Dockerfile, sem ruff/mypy, sem pre-commit, sem lockfile, sem `.env.example`, sem LICENSE.

## 2. Pontos fortes

- Camadas bem intencionadas (`apps/`, `domain/`, `infra/`, `rpa_core/`), módulos pequenos, estilo consistente, `from __future__ import annotations` e tipagem moderna em todo o projeto.
- Modelagem DB decente para o porte: unique/check constraints e índices sensatos (`infra/db/models.py:33-36, 52-56, 137-139, 169-173`).
- Fluxo **validate-before-publish** (`main.py:245-258`) e endpoint de validação dedicado.
- Secrets nunca vazam pela API (`SecretOut` sem valor, `schemas.py:132-138`; garantido por testes).
- `compare_digest` para a senha de exclusão (`main.py:5, 195`).
- Execução fixa a versão executada (`robot_version_id`) com imutabilidade garantida por teste.
- Recorder detecta campos de senha e gera `secret_fill` com placeholder em vez de gravar a senha (`playwright_recorder.py:51-54`).
- Retry e `timeout_ms` por step; screenshot de falha em timeout web (`executor.py:59-63, 74-84`).
- Erro amigável para Chromium ausente (`runs/service.py:75-79`).
- Testes usam monkeypatch com fakes (`FakeWorkflowExecutor`, `FakeDesktopController`) — o motor tem bons seams de teste.

## 3. Problemas críticos de segurança (P0)

1. **Zero autenticação em 36 endpoints — RCE não autenticado.** Nenhuma rota tem `Security`/API key/OAuth. Qualquer cliente que alcance a porta pode: `POST /robots/{id}/run` (`main.py:281-292`) com workflow contendo `command_run` (`executor.py:211-231`) → execução arbitrária de comandos; ou `file_read_text`/`file_delete` (`executor.py:190-194, 177-182`) → leitura/exclusão arbitrária de arquivos. O README sugere expor em `0.0.0.0` (`README.md:49`).
2. **Senha hardcoded `hendel#`** — `main.py:59` (`DELETE_PASSWORD = os.getenv(..., "hendel#")`), documentada em texto no `README.md:159` e fixada em `tests/test_api.py:143`. Sem rate limit nem lockout — brute-force trivial. É a única "autenticação" do sistema.
3. **Secrets protegidos por XOR, não criptografia** — `domain/secrets.py:16` (chave default `"dev-local-key"`) e `domain/secrets.py:39-47`: XOR repetitivo + base64. Reversível por qualquer um com acesso ao DB, sem sal/nonce/autenticidade, texto igual → ciphertext igual. A coluna `encrypted_value` (`infra/db/models.py:127`) dá falsa sensação de segurança.
4. **`command_run` sem sandbox/allowlist** — `executor.py:211-231`. Em `executor.py:220` o subprocess recebe `{**os.environ, **env}`, vazando o ambiente inteiro do servidor (incluindo `RPA_HUB_SECRET_KEY` e `RPA_HUB_DELETE_PASSWORD`).
5. **Passos de filesystem sem confinamento** — `_path()` em `executor.py:283-286` só faz `expanduser()`, sem allowlist de raízes. `file_delete` faz `shutil.rmtree` de qualquer caminho (`executor.py:177-182`).
6. **Zip-slip no `file_unzip`** — `executor.py:208-209` usa `extractall()` sem validar membros do ZIP → path traversal na extração.
7. **Recorder grava valores digitados em claro** — `playwright_recorder.py:54` persiste `target.value` de todo campo não-senha dentro do `workflow` JSON (`infra/db/models.py:43`).
8. **Auditoria sem identidade** — `actor` sempre `"system"` (`domain/audit.py:10`), sem IP, sem usuário; `/audit-events` aberto (`main.py:490-505`).
9. **Sem middleware de segurança** — sem CORS deliberado documentado, sem `TrustedHostMiddleware`, sem headers de segurança, sem limite de payload. Scripts de start rodam uvicorn com `--reload` (flag de dev) como padrão.

## 4. Problemas de arquitetura (P1)

1. **God file `main.py` (653 linhas / 36 rotas).** Sem `APIRouter`, sem tags OpenAPI. Mistura rotas HTTP, lógica de negócio (`_guided_workflow`, 76 linhas em `main.py:544-619`), mappers (`main.py:516-653`), orquestração de background (`main.py:508-513`) e singletons de infra (`scheduler`, `recorder_manager` — `main.py:61-62`).
2. **Rotas donas da transação.** Cada rota chama `session.commit()` manualmente enquanto os repositórios usam `flush()` — unit-of-work inconsistente. Rotas chamam `scheduler.reload()` (infra dentro da camada HTTP — `main.py:476, 486`). `get_session` sem rollback explícito em exceção (`main.py:79-84`).
3. **`domain` depende de `infra`** — inversão de dependência violada: `domain/robots/repository.py:8`, `domain/secrets.py:9`, `domain/runs/service.py:11`, `domain/audit.py:7` importam `infra.db.models` diretamente.
4. **Arquitetura de execução incorreta para o produto.** Runs rodam dentro do processo da API via `BackgroundTasks` (`main.py:291, 508-513`) e em threads do APScheduler (`infra/scheduler/service.py:60-67`). A tabela `workers` + heartbeat é decorativa: `local_worker.py:30-33` só manda heartbeat, nunca pega jobs — não existe fila, claim nem polling. Escalar horizontalmente é impossível; `uvicorn --workers 2` duplicaria o scheduler e executaria cada agenda N vezes.
5. **Motor sem registry de steps.** `_execute_step` é if/elif de ~190 linhas com 30 tipos (`executor.py:87-276`). Adicionar um step exige tocar 3 arquivos: `models.py`, `validation.py` e `executor.py`. `WorkflowStep` kitchen-sink: 26 campos opcionais (`rpa_core/engine/models.py:49-76`) — o modelo certo é union discriminada por `type`.
6. **N+1 queries.** `list_robots` chama `latest_version()` por robô (`main.py:148-150`); `_run_out` acessa `run.steps`/`run.artifacts` lazy por run (`main.py:539-540`) — `GET /runs` com `limit=50` dispara ~100+ selects. Sem `selectinload`.
7. **Sem timeout/cancelamento/recuperação de runs.** Runs travadas em `RUNNING` nunca se recuperam (lifespan `main.py:65-73` não reseta órfãos). Scheduler segura a thread durante a run inteira (`service.py:60-67`); sem `misfire_grace_time`/`coalescing`/`max_instances` (`service.py:52-58`).
8. **Cron não validado → 500.** `ScheduleCreate.cron` é string livre (`schemas.py:160`); `POST /schedules` não trata `ValueError` de `CronTrigger.from_crontab`.
9. **Race condition em versionamento.** `create_next_version` faz SELECT max + INSERT não atômico (`domain/robots/repository.py:95-109`) — concorrência viola a unique constraint com 500.
10. **Fuso horário inconsistente.** Datetimes naive UTC (`infra/time.py:6-7`), scheduler cravado em `America/Sao_Paulo` (`service.py:23`), templates com `date.today()` local (`rpa_core/variables/templating.py:12`).
11. **SQLite sem tuning.** Sem WAL nem `busy_timeout` (`infra/db/session.py:10-17`) — runs concorrentes produzem `database is locked`. `RunService` mantém a sessão aberta durante toda a execução Playwright (`domain/runs/service.py:35-73`).
12. **Schemas frouxos em pontos-chave.** `GuidedRobotCreate.template` string livre (typo degrada silenciosamente); `robots.status` sem CHECK constraint; sem limites para `timeout_ms`/`retry`/`seconds` — `delay` pode dormir por horas.
13. **`/teach/record` bloqueia uma thread do threadpool** por `seconds` (default 60) abrindo navegador visível no servidor (`main.py:357-368`); `RecorderManager` acumula sessões em dict para sempre — leak (`playwright_recorder.py:78, 86-88`).
14. **API design:** creates retornam 200 (não 201 + Location); sem paginação em `/robots`, `/workers`, `/secrets`, `/schedules`; `/audit-events` sem `response_model`.

## 5. Débitos técnicos

- **Hardcoded:** senha `hendel#` (`main.py:59`); chave de secrets `dev-local-key` (`domain/secrets.py:16`); timezone `America/Sao_Paulo` (`service.py:23`); URLs/porta default espalhadas.
- **structlog fantasma:** dependência declarada, zero uso; nenhum log em todo o código — exceções em background tasks são invisíveis (sem try/except em `_execute_run_background`, `main.py:508-513`); worker usa `print` (`local_worker.py:28, 32`).
- **create_all em vez de migrations:** qualquer mudança de schema exige apagar o DB.
- **Worker sem robustez:** `while True` sem try/except — um erro de rede derruba o processo; sem backoff, shutdown gracioso, token ou polling de jobs; sem `[project.scripts]` no `pyproject.toml`.
- **Erros brutos em `run.error`:** `str(exc)` persistido pode vazar paths internos (`domain/runs/service.py:64-67`).
- **Dependências sem lockfile/upper bounds:** só `>=` no `pyproject.toml`.
- **Steps web + file no mesmo contexto:** se há qualquer step web, todos os steps rodam dentro de `with sync_playwright()` — navegador aberto durante operações longas de arquivo/comando (`executor.py:53-58`).
- **Desktop:** coordenadas absolutas (frágeis a resolução), sem tratamento para servidor headless; steps desktop via API aberta = controle remoto do GUI do host.

## 6. Testes

- 16 testes para ~2.700 LOC — ok para API feliz + motor de arquivos/desktop, mas **zero testes** para scheduler, cripto de secrets, recorder, worker, templating de borda, erros 500, concorrência.
- Sem `conftest.py`: hack de env em module-level (`tests/test_api.py:3-5`), DB in-memory compartilhado entre testes sem isolamento.
- Sem `pytest-cov`, sem thresholds de cobertura, sem CI.

## 7. Plano de melhorias priorizado

### P0 — Segurança (bloqueia qualquer exposição em rede)

1. **Autenticação em toda a API** (API key ou OAuth2/OIDC) + remoção da senha estática de delete; rate limiting e `TrustedHostMiddleware`.
2. **Criptografia real dos secrets** (AES-GCM/Fernet, chave via env/KMS, sem default) substituindo o XOR + rotação dos valores existentes.
3. **Sandbox dos steps perigosos:** allowlist de binários para `command_run`, allowlist de raízes de filesystem para `file_*`, proteção zip-slip em `file_unzip`; não repassar `os.environ` inteiro ao subprocess.
4. **Remover valores digitados do recorder** do workflow persistido (mascarar/parametrizar).
5. **Healthcheck + hardening de deploy:** endpoint `/health`, remover `--reload` dos scripts de start, aviso/erro ao bindar `0.0.0.0` sem auth.

### P1 — Arquitetura / profissionalização

6. **Quebrar `main.py`** em `APIRouter` por recurso + camada de serviço; mover `_guided_workflow` para domain; unit-of-work consistente (commits fora das rotas).
7. **Fila real de execução:** tabela de jobs com claim/polling pelo worker (ou Celery/RQ), remover execução via `BackgroundTasks`; worker com try/except, backoff e shutdown gracioso; recovery de runs `RUNNING` no startup.
8. **Alembic** substituindo `create_all`.
9. **Logging estruturado com structlog** em API/worker/executor + handler global de exceções + request IDs; base para métricas Prometheus depois.
10. **Refatorar o motor:** registry de handlers de step + union discriminada por tipo; timeout global por run + cancelamento; bounds para `timeout_ms`/`retry`.
11. **Corrigir N+1** (`selectinload`) e adicionar paginação; validar cron no schema (422 em vez de 500); estratégia única de timezone (UTC aware).
12. **Testes:** `conftest.py` com DB isolado por teste; testes para scheduler/secrets/recorder/worker; `pytest-cov` com limite mínimo; **GitHub Actions** (ruff + mypy + pytest).

### P2 — Polish / DevOps

13. `Dockerfile` (base Playwright + deps de desktop) + `docker-compose`; `.env.example`; `LICENSE`.
14. Config de **ruff + mypy (strict)** + pre-commit; lockfile (uv) com pins.
15. Frontend: extrair o `index.html` para build (Vite) ou ao menos cachear a leitura.
16. `[project.scripts]` para o worker; OpenAPI com tags/summaries; status codes REST corretos (201/204); `PATCH /schedules` editável.
17. WAL + `busy_timeout` no SQLite enquanto não migrar de engine.

## 8. Síntese

Projeto com bom esqueleto (camadas, versionamento de workflows, validate-before-publish, imutabilidade da versão executada, testes com seams), mas **não está pronto para exposição em rede**: a combinação "0 autenticação + `command_run`/`file_*` sem sandbox + secrets em XOR + senha hardcoded" constitui RCE não autenticado por design.

**Ordem recomendada:** P0 (segurança) → P1 (god file, fila de jobs, migrations, logging) → P2 (DevOps).

# HUB RPA

Aplicacao de automacao robotica de processos para criar, versionar, executar e monitorar robos web com Python, FastAPI, SQLite e Playwright.

## Modulos entregues

- Dashboard operacional com robos, workers, agendas e execucoes.
- Cadastro de robos com workflow JSON versionado.
- Publicacao de versoes e criacao de novas versoes draft.
- Execucao manual em background, com status, logs e artefatos.
- Motor Playwright com blocos `goto`, `click`, `fill`, `secret_fill`, `select`, `press`, `wait_for`, `assert_text`, `download`, `screenshot` e `delay`.
- Cofre de segredos local para referencias como `portal.password`.
- Workers cadastraveis por maquina, tags e heartbeat.
- Agendas persistidas em SQLite com formato cron.
- Auditoria de criacao, publicacao, execucao, segredo, worker e agenda.
- Inicio do Modo Ensinar por gravacao assistida de navegador.

## Instalar

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

## Rodar o hub

```bash
uvicorn apps.api.rpa_hub_api.main:app --reload --host 127.0.0.1 --port 8010
```

Acesse:

- Hub: http://127.0.0.1:8010
- API: http://127.0.0.1:8010/docs

O banco padrao e `rpa_hub.db` na raiz do projeto. Para usar outro SQLite:

```bash
RPA_HUB_DATABASE_URL=sqlite:///./outro_banco.db uvicorn apps.api.rpa_hub_api.main:app --reload --port 8010
```

## Rodar worker local

```bash
python apps/worker/local_worker.py --hub http://127.0.0.1:8010 --name AUTO-01 --tags windows,local,playwright,excel
```

## Criar robo sem JSON

1. Abra http://127.0.0.1:8010.
2. Entre em **Studio**.
3. Em **1. Projeto do robo**, informe o nome, escolha a finalidade e indique o site inicial.
4. Clique em **Criar e continuar**.
5. Em **2. Ensinar**, clique em **Iniciar ensino**.
6. O HUB abre o Chromium. Faca o processo normalmente no site.
7. Volte ao HUB e clique em **Finalizar ensino**.
8. Confira os passos e clique em **Aprovar ensino**.
9. Em **3. Execucao**, escolha se o robo sera manual, diario, de segunda a sexta ou executado a cada hora.
10. Salve a configuracao ou clique em **Executar em segundo plano**.

Para aprender o fluxo sem cadastrar um site, use **Criar teste pronto** na primeira etapa. O JSON fica disponivel somente em **Ferramentas avancadas**.

## Exemplo interno de workflow

```json
{
  "inputs": {
    "data_inicio": "2026-09-01",
    "data_fim": "2026-09-01"
  },
  "steps": [
    { "type": "goto", "url": "https://example.com" },
    { "type": "wait_for", "target": { "text": "Example Domain" }, "timeout_ms": 10000 },
    { "type": "screenshot", "name": "home-{{run_date}}" }
  ]
}
```

## Exemplo com segredo

Crie um segredo chamado `portal.password` na tela Segredos. Depois use:

```json
{
  "inputs": {},
  "steps": [
    { "type": "goto", "url": "https://portal.local/login" },
    { "type": "fill", "target": { "label": "Usuario" }, "value": "meu.usuario" },
    { "type": "secret_fill", "target": { "label": "Senha" }, "secret": "portal.password" },
    { "type": "click", "target": { "role": "button", "name": "Entrar" } }
  ]
}
```

## Agendas

As agendas usam cron de 5 campos:

```text
0 7 * * 1-5
```

Isso representa 07:00 de segunda a sexta. Quando `apscheduler` estiver instalado, o hub carrega agendas ativas no startup e as recarrega ao criar ou pausar uma agenda.

## Modo Ensinar

Endpoints principais:

```bash
curl -X POST http://127.0.0.1:8010/robots/1/teach/start \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com"}'
```

Depois finalize usando o `session_id` retornado:

```bash
curl -X POST http://127.0.0.1:8010/robots/1/teach/stop/SESSION_ID
```

Ele abre um Chromium visivel, grava eventos ate o usuario finalizar, detecta links de download e nao salva valores digitados em campos de senha.

## Testes

```bash
pytest -q
```

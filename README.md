# HUB RPA

Aplicacao de automacao robotica de processos para criar, versionar, executar e monitorar robos web com Python, FastAPI, SQLite e Playwright.

## Modulos entregues

- Dashboard operacional com robos, workers, agendas e execucoes.
- Cadastro de robos com workflow JSON versionado.
- Publicacao de versoes e criacao de novas versoes draft.
- Execucao manual em background, com status, logs e artefatos.
- Motor Playwright com blocos `goto`, `click`, `fill`, `secret_fill`, `select`, `press`, `wait_for`, `assert_text`, `download`, `screenshot` e `delay`.
- Cofre de credenciais local para referencias como `portal.password`.
- Workers cadastraveis por maquina, tags e heartbeat.
- Agendas persistidas em SQLite com formato cron.
- Auditoria de criacao, publicacao, execucao, credencial, worker e agenda.
- Inicio do Modo Ensinar por gravacao assistida de navegador.

## Instalar

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

## Rodar o hub

Linux:

```bash
./start-linux.sh
```

Windows:

```bat
start-windows.bat
```

Os scripts criam o ambiente virtual `.venv`, instalam as dependencias, garantem o Chromium do Playwright e iniciam o Hub em `http://127.0.0.1:8010`.

Para trocar host ou porta:

Linux:

```bash
APP_HOST=0.0.0.0 APP_PORT=8020 ./start-linux.sh
```

Windows:

```bat
set APP_HOST=0.0.0.0
set APP_PORT=8020
start-windows.bat
```

Comando manual equivalente:

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
3. Em **1. Projeto do robo**, informe o nome, escolha a finalidade e indique o site inicial somente se o robo usar navegador.
4. Clique em **Criar e continuar**.
5. Em **2. Ensinar**, clique em **Iniciar ensino** se precisar gravar um site.
6. O HUB abre o Chromium. Faca o processo normalmente no site.
7. Volte ao HUB e clique em **Finalizar ensino**.
8. Confira os passos e clique em **Aprovar ensino**.
9. Em **3. Execucao**, escolha se o robo sera manual, diario, de segunda a sexta ou executado a cada hora.
10. Salve a configuracao ou clique em **Executar em segundo plano**.

Para automacoes locais de Windows/Linux, nao precisa informar site. Adicione os passos em **Ferramentas avancadas**, aprove o ensino e execute quando quiser. Para aprender o fluxo sem cadastrar um site, use **Criar teste pronto** na primeira etapa.

## Executar um robo treinado depois

Depois que um robo ja foi ensinado uma vez, ele pode ser usado quando voce quiser:

1. Abra o Hub.
2. Em **Studio**, escolha o robo na lista **Meus robos**.
3. Clique em **Ativar** para aprovar o ultimo ensino valido.
4. Depois disso, clique em **Executar** sempre que quiser rodar o robo em segundo plano.

Robos em `draft` ainda podem ser editados ou ensinados novamente. Robos `active` possuem uma versao publicada pronta para execucao.

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

## Exemplo com credencial

Crie uma credencial chamada `portal.password` na tela **Credenciais**. Depois selecione o robo em **Studio** e vincule essa credencial em **Credenciais deste robo**.

No passo de login, use `secret_fill` referenciando o nome da credencial:

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

O valor da senha nao aparece no workflow, nos logs ou na tela. O robo guarda somente o nome da credencial, por exemplo `portal.password`, e o Hub busca o valor real apenas na hora da execucao.

## Automacao do sistema operacional

O mesmo robo tambem pode executar passos locais no Windows ou Linux sem precisar de site:

- `file_create_folder`: cria uma pasta.
- `file_write_text`: cria ou atualiza um arquivo de texto.
- `file_copy`: copia arquivo ou pasta.
- `file_move`: move arquivo ou pasta.
- `file_delete`: apaga arquivo ou pasta.
- `file_read_text`: le um arquivo de texto e guarda em uma variavel do fluxo.
- `file_zip`: compacta arquivo ou pasta em ZIP.
- `file_unzip`: extrai um ZIP.
- `command_run`: executa um programa ou comando local.

Exemplo:

```json
{
  "inputs": {
    "cliente": "hmb"
  },
  "steps": [
    { "type": "file_create_folder", "path": "C:\\RPA\\{{cliente}}" },
    { "type": "file_write_text", "path": "C:\\RPA\\{{cliente}}\\status.txt", "value": "Processado", "overwrite": true },
    { "type": "file_copy", "source": "C:\\Downloads\\relatorio.xlsx", "destination": "C:\\RPA\\{{cliente}}\\relatorio.xlsx", "overwrite": true }
  ]
}
```

No Linux, use caminhos como `/home/usuario/rpa/relatorio.xlsx`. Quando o fluxo tiver somente passos de arquivo/pasta, o Hub nao abre o navegador.

Exemplo chamando um programa/script externo:

```json
{
  "inputs": {},
  "steps": [
    {
      "type": "command_run",
      "command": "python",
      "args": ["scripts/processar.py", "--cliente", "HMB"],
      "cwd": "C:\\RPA",
      "output_name": "saida-processamento",
      "timeout_ms": 120000
    },
    {
      "type": "file_zip",
      "source": "C:\\RPA\\saida",
      "destination": "C:\\RPA\\saida.zip",
      "overwrite": true
    }
  ]
}
```

Para comandos do terminal, prefira informar o programa e os argumentos separados. Exemplos: `["-c", "echo ok"]` com `bash`, ou `["/c", "dir"]` com `cmd`.

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

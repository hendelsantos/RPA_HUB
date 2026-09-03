# HUB RPA

Aplicacao de automacao robotica de processos para criar, versionar, executar e monitorar robos web com Python, FastAPI, SQLite e Playwright.

## Modulos entregues

- Tela unica de Logs com indicadores, historico de execucoes, detalhes e artefatos.
- Filtros de logs por robo e status, linha do tempo por execucao e download de artefatos.
- Sugestoes de correcao quando um passo de navegador nao encontra campo, botao, menu ou link.
- Cadastro de robos com workflow JSON versionado.
- Criacao de copias e backup/restauracao de robos em JSON.
- Publicacao de versoes e criacao de novas versoes draft.
- Execucao manual em background, com status, logs e artefatos.
- Motor Playwright com blocos `goto`, `click`, `fill`, `secret_fill`, `select`, `press`, `wait_for`, `assert_text`, `download`, `screenshot` e `delay`.
- Automacao local com mouse, teclado, arquivos, pastas, ZIP e comandos.
- Diagnostico do ambiente para avisar quando o controle de mouse/teclado nao esta disponivel.
- Cofre de credenciais local para referencias como `portal.password`.
- Workers cadastraveis por maquina, tags e heartbeat.
- Agendas persistidas em SQLite com formato cron.
- Auditoria de criacao, publicacao, execucao, credencial, worker e agenda.
- Inicio do Modo Ensinar por gravacao assistida de navegador.
- Gravador de navegador com seletores melhores, variaveis automaticas e senha como credencial.
- Editor visual com resumo de cada passo e acoes para duplicar, mover e desativar sem apagar.
- Fila local de execucao com limite de concorrencia, recuperacao de execucoes interrompidas e cancelamento.

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
APP_HOST=0.0.0.0 APP_PORT=8020 RPA_HUB_API_KEY=uma-chave-forte ./start-linux.sh
```

Windows:

```bat
set APP_HOST=0.0.0.0
set APP_PORT=8020
set RPA_HUB_API_KEY=uma-chave-forte
start-windows.bat
```

Comando manual equivalente:

```bash
uvicorn apps.api.rpa_hub_api.main:app --host 127.0.0.1 --port 8010
```

Acesse:

- Hub: http://127.0.0.1:8010
- API: http://127.0.0.1:8010/docs
- Status: http://127.0.0.1:8010/health

O banco padrao e `rpa_hub.db` na raiz do projeto. Para usar outro SQLite:

```bash
RPA_HUB_DATABASE_URL=sqlite:///./outro_banco.db uvicorn apps.api.rpa_hub_api.main:app --port 8010
```

## Seguranca e acesso

- **Acesso local (padrao):** sem configuracao, o Hub aceita somente conexoes da propria maquina (`127.0.0.1`). Nenhuma senha e necessaria.
- **Acesso em rede:** defina `RPA_HUB_API_KEY` no servidor. Todas as chamadas da API passam a exigir o cabecalho `X-API-Key`. A interface web pede a chave automaticamente na primeira conexao e guarda no navegador. Chamadas sem chave ou com chave errada recebem `401`.
- **Credenciais:** os valores do cofre sao cifrados com AES (Fernet). A chave e gerada automaticamente no arquivo `.rpa_hub_secret.key` (na raiz, ignorado pelo git) ou definida pela variavel `RPA_HUB_SECRET_KEY`. Para usar em rede ou backup, gere uma chave com:

  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

- **Senha de exclusao (opcional):** por padrao, excluir robo exige apenas a chave da API. Para pedir uma confirmacao extra, defina `RPA_HUB_DELETE_PASSWORD`.
- **Limites dos passos:** `timeout_ms` e limitado (padrao 1 hora, ajustavel com `RPA_HUB_MAX_STEP_TIMEOUT_MS`) e `retry` aceita no maximo 5.
- **Sandbox (opcional):** `RPA_HUB_ALLOWED_ROOTS` restringe os passos de arquivo a pastas especificas e `RPA_HUB_ALLOWED_COMMANDS` restringe quais programas o passo `command_run` pode executar. Exemplo: `RPA_HUB_ALLOWED_ROOTS=C:\RPA,D:\Entradas RPA_HUB_ALLOWED_COMMANDS=python,powershell`. Sem essas variaveis, o robo opera como antes, mas comandos nunca recebem as variaveis de ambiente internas do servidor (como chaves e senhas).
- A extracao de ZIP valida cada arquivo e bloqueia arquivos que tentem escapar da pasta de destino.

Na tela **Credenciais**, o botao **Testar** confirma se o Hub consegue abrir a credencial cifrada sem mostrar o valor. Em **Credenciais deste robo**, use um apelido estavel, como `senha.portal`; depois, os passos podem referenciar esse apelido e voce consegue trocar a credencial vinculada sem editar o workflow.

## Rodar worker local

```bash
python apps/worker/local_worker.py --hub http://127.0.0.1:8010 --name AUTO-01 --tags windows,local,playwright,excel
```

## Criar robo sem JSON

1. Abra http://127.0.0.1:8010.
2. Entre em **Studio**.
3. Em **1. Projeto do robo**, informe o nome, escolha a finalidade e indique o site inicial somente se o robo usar navegador.
4. Clique em **Criar e continuar**.
5. Em **2. Ensinar**, clique em **Gravar site** se precisar gravar um site.
6. O HUB abre o Chromium. Faca o processo normalmente no site.
7. Volte ao HUB e clique em **Parar gravacao**.
8. Confira os passos e clique em **Salvar robo**.
9. Em **3. Execucao**, escolha se o robo sera manual, diario, de segunda a sexta ou executado a cada hora.
10. Salve a configuracao ou clique em **Salvar e executar**.

Para automacoes locais de Windows/Linux, nao precisa informar site. Adicione os passos em **Ferramentas avancadas**, aprove o ensino e execute quando quiser. Para aprender o fluxo sem cadastrar um site, use **Criar teste pronto** na primeira etapa.

## Executar um robo treinado depois

Depois que um robo ja foi ensinado uma vez, ele pode ser usado quando voce quiser:

1. Abra o Hub.
2. Em **Studio**, escolha o robo na lista **Meus robos**.
3. Clique em **Ativar** para aprovar o ultimo ensino valido.
4. Depois disso, clique em **Executar** sempre que quiser rodar o robo em segundo plano.

Robos em `draft` ainda podem ser editados ou ensinados novamente. Robos `active` possuem uma versao publicada pronta para execucao.

## Variaveis de execucao

Em **Studio > Ensinar > Ferramentas avancadas**, use **Variaveis do robo** para criar entradas reutilizaveis, como:

- `cliente`
- `data_inicio`
- `data_fim`
- `pasta_destino`

Depois use essas variaveis nos passos com `{{nome_da_variavel}}`.

Exemplo:

```json
{
  "inputs": {
    "cliente": "HMB",
    "pasta_destino": "C:\\RPA\\HMB"
  },
  "steps": [
    { "type": "file_create_folder", "path": "{{pasta_destino}}" },
    { "type": "file_write_text", "path": "{{pasta_destino}}\\cliente.txt", "value": "{{cliente}}", "overwrite": true }
  ]
}
```

Na etapa **3. Execucao**, o Hub mostra essas entradas para voce alterar antes de rodar ou salvar uma agenda.

## Modelos rapidos

Em **Studio > Ensinar > Ferramentas avancadas**, use **Modelos rapidos** para inserir blocos prontos no robo:

- **Baixar arquivo de sistema**
- **Pesquisar no Google**
- **Entrar em site com senha**
- **Pasta + arquivo**
- **Copiar + ZIP**
- **Executar comando**
- **Abrir site + evidencia**
- **Desktop simples**

Depois de inserir um modelo, ajuste os campos, confira os passos e clique em **Salvar robo**.

Para um fluxo comum de trabalho, use **Baixar arquivo de sistema**. Ele cria passos para abrir o sistema, preencher usuario e senha, entrar, abrir a aba de relatorios, filtrar pelo `{{modelo}}`, baixar o arquivo e salvar uma evidencia. Ajuste os textos dos campos e botoes para os nomes reais que aparecem no seu sistema.

Quando um passo de navegador falhar, a tela de Logs mostra **Como corrigir** e salva um print da tela no momento do erro quando possivel. Use essa evidencia para ajustar o nome do campo, botao, menu ou link.

## Gerenciar robos

Na lista **Meus robos**:

- **Continuar** abre o robo para editar os passos atuais.
- **Reconfigurar** cria uma nova versao `draft` a partir da versao atual e deixa o robo pronto para ajuste.
- **Criar copia** cria outro robo igual para voce ajustar sem mexer no original.
- **Baixar backup** salva um arquivo JSON com dados principais e workflow.
- **Restaurar backup** cria um robo a partir de um arquivo JSON salvo anteriormente.
- **Ativar** aprova o ultimo ensino valido.
- **Executar** roda o robo ativo em segundo plano.
- **Excluir** remove o robo, suas versoes, agendas, execucoes e vinculos de credenciais.

A exclusao pede confirmacao. Se o servidor tiver `RPA_HUB_DELETE_PASSWORD` definida, ele tambem pede essa senha.

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

## Conectores praticos

Na mesma lista de passos avancados, o Hub tambem possui conectores para processos comuns:

- `csv_read` e `csv_write`: leem e geram CSV.
- `excel_read` e `excel_write`: leem e geram `.xlsx`.
- `api_request`: chama APIs HTTP e pode salvar a resposta como evidencia JSON.
- `email_send`: envia email por SMTP usando credencial do cofre para a senha.
- `db_query`: executa consulta em banco SQLite e pode salvar resultado em CSV.
- `folder_wait_for_file`: espera um arquivo aparecer em uma pasta.
- `pdf_from_text`: gera uma evidencia em PDF simples a partir de texto.

Para gerar tabelas, informe os dados como JSON no campo valor, por exemplo `[{"cliente":"HMB","status":"ok"}]`, ou leia primeiro um CSV/Excel para uma variavel e reutilize essa variavel no passo seguinte.

Para controlar mouse e teclado com passos `desktop_*`, o Hub precisa estar rodando na mesma sessao grafica do usuario. Em Linux, se aparecer mensagem sobre `DISPLAY` ou `XAUTHORITY`, use robos de navegador/arquivos ou reinicie o Hub dentro da tela grafica correta.

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

## Automacao de mouse e teclado

Para sistemas que nao tem API ou site facil de automatizar, o robo pode controlar a sessao grafica da maquina:

- `desktop_move`: move o mouse para `x` e `y`.
- `desktop_click`: clica na tela.
- `desktop_double_click`: da duplo clique.
- `desktop_drag`: arrasta o mouse.
- `desktop_type`: digita texto.
- `desktop_press`: pressiona uma tecla.
- `desktop_hotkey`: executa atalhos como `ctrl+s` ou `alt+tab`.
- `desktop_screenshot`: tira print da tela como evidencia.
- `desktop_wait`: aguarda um tempo.

Exemplo:

```json
{
  "inputs": {},
  "steps": [
    { "type": "desktop_hotkey", "keys": ["win", "r"] },
    { "type": "desktop_type", "value": "notepad", "interval_ms": 20 },
    { "type": "desktop_press", "key": "enter" },
    { "type": "desktop_wait", "timeout_ms": 1000 },
    { "type": "desktop_type", "value": "Processo executado pelo HUB RPA" },
    { "type": "desktop_hotkey", "keys": ["ctrl", "s"] },
    { "type": "desktop_screenshot", "name": "notepad-aberto" }
  ]
}
```

Essa automacao controla o mouse e o teclado reais da maquina que executa o worker. No Linux, ela precisa de uma sessao grafica ativa; em servidores sem tela, use passos de arquivo/comando ou configure um desktop virtual.

## Agendas

As agendas usam cron de 5 campos:

```text
0 7 * * 1-5
```

Isso representa 07:00 de segunda a sexta. Quando `apscheduler` estiver instalado, o hub carrega agendas ativas no startup e as recarrega ao criar ou pausar uma agenda.

## Modo Ensinar

Endpoints principais (adicione o cabecalho `-H 'X-API-Key: ...'` quando o Hub estiver com `RPA_HUB_API_KEY` configurada):

```bash
curl -X POST http://127.0.0.1:8010/robots/1/teach/start \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com"}'
```

Depois finalize usando o `session_id` retornado:

```bash
curl -X POST http://127.0.0.1:8010/robots/1/teach/stop/SESSION_ID
```

Ele abre um Chromium visivel, grava eventos ate o usuario finalizar, detecta links de download, nao salva valores digitados em campos de senha e converte campos de texto digitados em variaveis `campo_1`, `campo_2`... para voce preencher na execucao (o valor digitado nao fica salvo).

## Testes

```bash
pytest -q
```

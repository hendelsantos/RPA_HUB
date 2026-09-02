# Roadmap de melhorias do HUB RPA

Este documento organiza as proximas melhorias para transformar o HUB RPA em um produto mais profissional, facil de usar e forte para automacoes reais em Windows, Linux, navegador e desktop.

## Prioridade atual

A prioridade agora e executar a **Prioridade 2 - Automacao mais poderosa**.

Motivo: o produto ja ganhou uma base visual melhor e agora precisa permitir automacoes reutilizaveis, com entradas variaveis, modelos e captura de desktop.

Ordem recomendada para a proxima etapa:

1. Finalizar **Variaveis amigaveis** antes da execucao.
2. Criar **Biblioteca de modelos** para robos comuns.
3. Evoluir o **Gravador de desktop**.
4. Melhorar automacoes guiadas pelo navegador e pelo desktop.

Credenciais avancadas ficam para depois. O produto tambem nao precisa de instalador Windows neste momento, porque a operacao sera feita pela interface web.

Depois disso, faz sentido seguir para fila inteligente, permissoes e notificacoes.

## Prioridade 1 - Usabilidade principal

### 1. Construtor visual de passos

Problema atual: a tela de **Ferramentas avancadas** mostra muitos campos ao mesmo tempo. Isso confunde porque campos de site, arquivo, comando, mouse e credencial aparecem juntos.

Melhoria:

- Mostrar somente os campos relevantes para o tipo de passo escolhido. **Iniciado.**
- Separar os tipos em grupos: navegador, arquivo/pasta, comandos, desktop e evidencias. **Iniciado.**
- Validar campos antes de adicionar o passo.
- Melhorar o resumo visual de cada passo.

Resultado esperado: o usuario consegue montar robos sem entender JSON.

### 2. Assistente de criacao de robos

Problema atual: o usuario precisa saber quais passos adicionar.

Melhoria:

- Criar modelos prontos:
  - acessar site com login
  - baixar relatorio
  - mover/copiar arquivos
  - executar programa
  - controlar mouse e teclado
  - compactar arquivos
- Gerar os primeiros passos automaticamente a partir das respostas.

Resultado esperado: criar robos comuns em poucos cliques.

### 3. Logs operacionais melhores

Problema atual: a tela de logs ainda mostra informacoes tecnicas demais.

Melhoria:

- Linha do tempo por execucao.
- Status por passo.
- Duracao por passo.
- Artefatos clicaveis.
- Evidencia de erro destacada.
- Filtro por robo, status e data.

Resultado esperado: entender falhas rapidamente.

### 4. Painel do robo

Problema atual: as acoes do robo ficam espalhadas.

Melhoria:

- Criar uma area unica do robo com:
  - dados gerais
  - passos
  - versoes
  - agendas
  - ultima execucao
  - botoes de executar, ativar, reconfigurar, duplicar e excluir

Resultado esperado: cada robo fica facil de operar e manter.

## Prioridade 2 - Automacao mais poderosa

### 5. Gravador de desktop

Melhoria:

- Capturar cliques, teclas e coordenadas.
- Gerar passos `desktop_*`.
- Permitir revisar antes de salvar.

### 6. Variaveis amigaveis

Melhoria:

- Definir entradas do robo, como cliente, datas e pasta destino. **Iniciado.**
- Pedir essas entradas antes de executar. **Iniciado.**
- Usar essas variaveis em caminhos, textos, comandos e URLs. **Iniciado.**

### 7. Biblioteca de modelos

Melhoria:

- Templates reutilizaveis de workflow. **Iniciado.**
- Importar/exportar robos em JSON.
- Duplicar robos existentes.

## Prioridade 3 - Produto e operacao

### 9. Usuarios e permissoes

Melhoria:

- Admin, operador e visualizador.
- Proteger exclusao e configuracoes criticas.

### 10. Fila inteligente

Melhoria:

- Evitar duas automacoes de desktop usando mouse/teclado ao mesmo tempo.
- Distribuir execucoes entre workers.
- Mostrar maquina responsavel por cada execucao.

### 11. Operacao web

Melhoria:

- Interface web unica para criar, configurar, executar e acompanhar robos.
- Documentacao simples para iniciar o Hub em rede local.
- Status claro do ambiente em uso.

### 12. Monitoramento e notificacoes

Melhoria:

- Alertas de falha por email, Teams ou WhatsApp.
- Status de workers.
- Historico de disponibilidade.

## Ordem recomendada de execucao

1. Construtor visual de passos.
2. Painel do robo.
3. Logs operacionais melhores.
4. Variaveis amigaveis.
5. Assistente de criacao com modelos.
6. Fila inteligente para desktop.
7. Operacao web.
8. Notificacoes.

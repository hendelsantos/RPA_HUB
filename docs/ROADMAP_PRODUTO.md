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

Atualizacao da fase 5: a fila local agora registra a maquina executora, permite cancelamento,
recupera execucoes interrompidas e aceita repeticao automatica apos falha em execucoes manuais
e agendadas.

Atualizacao da fase 6: credenciais continuam cifradas, podem ser testadas sem expor valor,
podem ser vinculadas ao robo por apelido estavel e trocadas depois sem editar os passos.
Perfis de usuario e login obrigatorio ficaram adiados para manter o uso local simples.

Atualizacao da fase 7: o motor ganhou conectores para CSV, Excel, API HTTP, email SMTP,
SQLite, monitoramento de pasta e PDF textual de evidencia, todos disponiveis no editor visual
de passos.

Atualizacao da fase 8: foi criada a aba Robo com painel operacional consolidado, incluindo
dados gerais, passos atuais, credenciais, ultima execucao, arquivos, agendas e acoes principais.

Atualizacao da fase 9: foi criada a aba Monitoramento com alertas de falha, historico recente,
tempo medio, taxa de sucesso, robos que precisam de ajuste, resumo diario e envio opcional por
email SMTP quando configurado.

Atualizacao da fase 10: o painel do robo ganhou um check de pronto para uso real. Ele consolida
passos, validacao, publicacao, credenciais, teste com sucesso, evidencias, agenda e alertas
abertos para mostrar o que falta antes de operar sem acompanhamento.

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

- Linha do tempo por execucao. **Iniciado.**
- Status por passo. **Iniciado.**
- Duracao por passo. **Iniciado.**
- Artefatos clicaveis. **Iniciado.**
- Evidencia de erro destacada. **Iniciado.**
- Filtro por robo, status e data. **Iniciado para robo e status.**
- Sugestoes de correcao quando campo, botao, menu ou link nao forem encontrados. **Iniciado.**

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
  - botoes de executar, ativar, reconfigurar, criar copia e excluir

Resultado esperado: cada robo fica facil de operar e manter.

## Prioridade 2 - Automacao mais poderosa

### 5. Gravador de desktop

Melhoria:

- Capturar cliques, teclas e coordenadas.
- Gerar passos `desktop_*`.
- Permitir revisar antes de salvar.

### 5.1 Gravador de navegador

Melhoria:

- Capturar cliques, campos, selecoes e downloads de forma mais limpa. **Iniciado.**
- Transformar textos digitados em variaveis com nomes amigaveis. **Iniciado.**
- Trocar campos de senha por credencial, sem salvar valor digitado. **Iniciado.**
- Reduzir passos duplicados gerados pela gravacao. **Iniciado.**

### 6. Variaveis amigaveis

Melhoria:

- Definir entradas do robo, como cliente, datas e pasta destino. **Iniciado.**
- Pedir essas entradas antes de executar. **Iniciado.**
- Usar essas variaveis em caminhos, textos, comandos e URLs. **Iniciado.**

### 7. Biblioteca de modelos

Melhoria:

- Templates reutilizaveis de workflow. **Iniciado.**
- Baixar e restaurar backup de robos em JSON. **Iniciado.**
- Criar copias de robos existentes. **Iniciado.**

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

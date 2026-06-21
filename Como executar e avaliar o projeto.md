# Como executar e avaliar o projeto

Este documento explica como utilizar os fontes Python do projeto **Escalonamento paralelo adaptativo inspirado no TCP para ambiente heterogêneo**. A implementação usa nomes em português para variáveis principais, mensagens e campos do banco SQLite.

## Modos de execução

| Modo | Arquivo principal | Papel na avaliação |
|---|---|---|
| Sequencial | `src/run_sequential.py` | Mede o tempo base para comparação. |
| Paralelo estático | `src/mestre.py --modo estatico` | Mede o ganho paralelo sem adaptação dinâmica. |
| Paralelo adaptativo | `src/mestre.py --modo adaptativo` | Mede o efeito da adaptação individual por trabalhador. |
| Teste local integrado | `src/run_local_experiment.py` | Inicia mestre e trabalhadores locais automaticamente. |
| Gráficos | `src/plot_results.py` | Gera visualizações a partir do SQLite. |

## Execução rápida em uma máquina

```bash
cd escalonamento_tcp_primos
python3 src/run_sequential.py --inicio 1000000 --fim 1200000 --banco resultados.db
```

Modo adaptativo com três trabalhadores locais:

```bash
python3 src/run_local_experiment.py \
  --inicio 1000000 \
  --fim 1400000 \
  --trabalhadores 3 \
  --modo adaptativo \
  --porta 9101 \
  --banco resultados.db \
  --tamanho-bloco-base 10000 \
  --tempo-alvo 0.4
```

Por padrão, cada trabalhador local detecta suas próprias CPUs disponíveis e usa esse valor como indicação de multiprocessamento. Se for necessário limitar artificialmente os processos por trabalhador em um teste local, use `--nucleos-trabalhador 1`, `--nucleos-trabalhador 2` e assim por diante.

Modo estático:

```bash
python3 src/run_local_experiment.py \
  --inicio 1000000 \
  --fim 1400000 \
  --trabalhadores 3 \
  --modo estatico \
  --porta 9102 \
  --banco resultados.db \
  --tamanho-bloco-base 10000
```

Geração de gráficos:

```bash
python3 src/plot_results.py --banco resultados.db --saida graficos
```

## Execução distribuída com sockets

No mestre, execute o processo escutando em todas as interfaces de rede com `--endereco 0.0.0.0`. O argumento `--max-trabalhadores` define o limite máximo aceito, que pode ser qualquer valor de **1 a 30**. Como os trabalhadores podem ser iniciados manualmente, o mestre aguarda novas conexões por `--tempo-espera-trabalhadores` segundos depois que `--min-trabalhadores` já tiver sido alcançado. Após iniciar o processamento, o mestre continua aceitando novos trabalhadores dinamicamente até atingir o limite máximo, desde que ainda exista trabalho pendente para distribuir.

```bash
python3 src/mestre.py \
  --endereco 0.0.0.0 \
  --porta 9000 \
  --max-trabalhadores 30 \
  --min-trabalhadores 1 \
  --tempo-espera-trabalhadores 60 \
  --timeout-heartbeat 180 \
  --intervalo-monitoramento-heartbeat 5 \
  --inicio 1000000 \
  --fim 5000000 \
  --modo adaptativo \
  --tamanho-bloco-base 10000 \
  --tempo-alvo 0.5 \
  --banco resultados.db
```

Em cada trabalhador, execute o processo informando o **IP real do mestre** e a mesma porta configurada no mestre. Cada trabalhador deve usar um `--id-trabalhador` único.

```bash
python3 src/trabalhador.py \
  --endereco-mestre IP_DO_MESTRE \
  --porta-mestre 9000 \
  --id-trabalhador trabalhador-01 \
  --intervalo-heartbeat 60
```

Como `--nucleos` é uma configuração local do trabalhador, ele é opcional. Quando omitido, o trabalhador usa `auto`, isto é, detecta as CPUs disponíveis em sua própria máquina. O mestre apenas recebe esse valor no registro do trabalhador para fins de log e armazenamento.

## Heartbeat e recuperação de tarefas

Cada trabalhador envia uma mensagem JSON `{"tipo": "heartbeat"}` ao mestre em intervalos regulares. O valor padrão é **60 segundos**, ajustável com `--intervalo-heartbeat`. O mestre, por sua vez, executa um monitor periódico que verifica há quanto tempo cada trabalhador ativo não envia heartbeat.

| Parâmetro | Onde é usado | Padrão | Descrição |
|---|---|---:|---|
| `--intervalo-heartbeat` | Trabalhador | `60` | Intervalo, em segundos, entre mensagens de heartbeat enviadas ao mestre. |
| `--timeout-heartbeat` | Mestre | `180` | Tempo máximo, em segundos, sem heartbeat antes de desconectar o trabalhador. |
| `--intervalo-monitoramento-heartbeat` | Mestre | `5` | Intervalo, em segundos, entre verificações de trabalhadores expirados. |

Se o mestre não receber heartbeat de um trabalhador durante **3 minutos** por padrão, ele considera esse trabalhador inativo, fecha a conexão e remove a instância da lista de trabalhadores ativos. Caso esse trabalhador estivesse processando uma tarefa, os blocos associados à tarefa são recolocados na fila de pendências para que outro trabalhador livre possa processá-los. Esse comportamento evita que uma falha de máquina, rede ou processo deixe parte do intervalo total sem contagem.

Para testes controlados de tolerância a falhas, é possível reduzir temporariamente os tempos de heartbeat. Por exemplo, o mestre pode ser iniciado com `--timeout-heartbeat 3 --intervalo-monitoramento-heartbeat 1`, enquanto um trabalhador saudável usa `--intervalo-heartbeat 1`. Em uma execução real, recomenda-se manter os padrões de 60 segundos para o envio e 180 segundos para o timeout.

| Parâmetro do mestre | Finalidade |
|---|---|
| `--endereco 0.0.0.0` | Faz o mestre aceitar conexões vindas de outras máquinas da rede. |
| `--porta 9000` | Define a porta TCP na qual os trabalhadores deverão conectar. |
| `--max-trabalhadores 30` | Define o máximo de trabalhadores aceitos pelo mestre. |
| `--min-trabalhadores 1` | Define o mínimo necessário para iniciar a execução. |
| `--tempo-espera-trabalhadores 60` | Define por quanto tempo o mestre aguarda antes de iniciar, depois que o mínimo de trabalhadores já foi alcançado. Após esse início, novos trabalhadores ainda podem entrar dinamicamente enquanto houver trabalho pendente. |
| `--timeout-heartbeat 180` | Define o limite de inatividade por heartbeat antes de desconectar um trabalhador. |
| `--intervalo-monitoramento-heartbeat 5` | Define a frequência da verificação interna de heartbeats expirados. |

## Campos das tabelas

| Tabela | Descrição |
|---|---|
| `execucoes` | Guarda cada rodada experimental, com `id_execucao`, `modo`, `valor_inicio`, `valor_fim`, `tamanho_bloco_base`, `tempo_alvo`, `segundos_totais`, `total_primos` e `vazao_numeros_por_segundo`. |
| `tarefas` | Guarda cada pacote enviado, identificado por `id_execucao` e `id_tarefa`, com `id_trabalhador`, `intervalos_json`, `quantidade_numeros`, `quantidade_primos`, `janela_antes`, `janela_depois` e tempos. |
| `trabalhadores` | Guarda estatísticas agregadas por trabalhador, como `numeros_processados`, `primos_encontrados` e `total_segundos_trabalhador`. |

## Relação com PCAM

| Etapa PCAM | Aplicação no código |
|---|---|
| Partitioning | O intervalo total é dividido em blocos menores, definidos por `--tamanho-bloco-base`. |
| Communication | O mestre envia tarefas por socket, recebe respostas com tempo, quantidade processada e primos encontrados, e monitora heartbeats dos trabalhadores. |
| Agglomeration | A janela controla o agrupamento de blocos em pacotes maiores ou menores. |
| Mapping | O mestre decide dinamicamente qual carga enviar para cada trabalhador com base em sua resposta anterior e devolve à fila as tarefas de trabalhadores desconectados. |

# Escalonamento paralelo adaptativo inspirado no TCP

Este projeto implementa, em Python, um protótipo de **escalonamento paralelo adaptativo** inspirado em conceitos da camada TCP. O sistema possui um processo **mestre**, vários **trabalhadores** e três modos de avaliação: execução sequencial, paralela estática e paralela adaptativa.

A versão atual usa nomes em português nas variáveis principais, nos campos das mensagens entre mestre e trabalhadores e nas tabelas SQLite. No mestre, os argumentos de linha de comando foram padronizados em português, e a distribuição de trabalho opera exclusivamente por blocos.

## Estrutura

| Arquivo | Função |
|---|---|
| `src/mestre.py` | Processo mestre responsável por distribuir blocos de intervalos, ajustar janelas, aceitar dinamicamente até 30 trabalhadores conectados manualmente por IP e porta, monitorar heartbeats e reenfileirar tarefas de trabalhadores inativos. |
| `src/trabalhador.py` | Processo trabalhador responsável por contar primos nos intervalos recebidos, detectar localmente seus próprios núcleos por padrão e enviar heartbeats periódicos ao mestre. |
| `src/run_sequential.py` | Linha de base sequencial. |
| `src/run_local_experiment.py` | Executa mestre e trabalhadores locais automaticamente. |
| `src/armazenamento.py` | Persistência SQLite com tabelas `execucoes`, `tarefas` e `trabalhadores`. |
| `src/plot_results.py` | Gera gráficos a partir do banco de resultados. |

## Execução rápida

```bash
python3 src/run_sequential.py --inicio 1000000 --fim 1200000 --banco resultados.db

python3 src/run_local_experiment.py \
  --inicio 1000000 \
  --fim 1400000 \
  --trabalhadores 3 \
  --modo adaptativo \
  --porta 9101 \
  --banco resultados.db \
  --tamanho-bloco-base 10000 \
  --tempo-alvo 0.4

python3 src/run_local_experiment.py \
  --inicio 1000000 \
  --fim 1400000 \
  --trabalhadores 3 \
  --modo estatico \
  --porta 9102 \
  --banco resultados.db \
  --tamanho-bloco-base 10000

python3 src/plot_results.py --banco resultados.db --saida graficos
```

Por padrão, o script de experimento local não força `--nucleos` nos trabalhadores. Cada trabalhador usa `auto` e detecta as CPUs disponíveis na própria máquina. O argumento `--nucleos-trabalhador` continua existindo apenas para limitar artificialmente o multiprocessamento local em testes controlados.

## Execução distribuída manual

Para uma execução em rede, primeiro inicie o mestre informando o endereço de escuta, a porta e o limite máximo de trabalhadores. O valor de `--max-trabalhadores` deve estar entre **1 e 30**. O mestre começa o processamento quando o limite é atingido ou quando passa o tempo configurado em `--tempo-espera-trabalhadores` depois que o mínimo configurado em `--min-trabalhadores` já foi alcançado. Mesmo após o início do processamento, o mestre continua aceitando trabalhadores dinamicamente até o limite máximo, desde que ainda existam tarefas pendentes a distribuir.

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
  --banco resultados.db
```

Depois, em cada máquina trabalhadora, execute o trabalhador apontando para o IP e a porta do mestre. Cada instância deve possuir um identificador único.

```bash
python3 src/trabalhador.py \
  --endereco-mestre IP_DO_MESTRE \
  --porta-mestre 9000 \
  --id-trabalhador trabalhador-01 \
  --intervalo-heartbeat 60
```

## Heartbeat e tolerância a falhas

O trabalhador envia periodicamente ao mestre uma mensagem JSON do tipo `heartbeat`. O intervalo padrão é de **60 segundos**, configurável no trabalhador com `--intervalo-heartbeat`. O mestre mantém, para cada conexão ativa, o instante do último heartbeat recebido e executa uma thread de monitoramento independente.

| Componente | Parâmetro | Valor padrão | Finalidade |
|---|---:|---:|---|
| Trabalhador | `--intervalo-heartbeat` | `60` | Define o intervalo, em segundos, entre heartbeats enviados ao mestre. |
| Mestre | `--timeout-heartbeat` | `180` | Define o tempo máximo, em segundos, sem heartbeat antes de considerar o trabalhador inativo. |
| Mestre | `--intervalo-monitoramento-heartbeat` | `5` | Define a periodicidade, em segundos, da verificação interna de expiração dos heartbeats. |

Quando um trabalhador fica inativo por mais tempo que `--timeout-heartbeat`, o mestre fecha sua conexão, remove o trabalhador da lista de ativos e verifica se havia uma tarefa em andamento associada a ele. Se houver, os blocos dessa tarefa são devolvidos à fila de pendências para que outro trabalhador possa processá-los. Resultados tardios vindos de um trabalhador já desconectado são ignorados, evitando dupla contagem.

## Campos principais do SQLite

| Tabela | Campos principais |
|---|---|
| `execucoes` | `id_execucao`, `modo`, `valor_inicio`, `valor_fim`, `segundos_totais`, `total_primos`, `vazao_numeros_por_segundo`. |
| `tarefas` | `id_tarefa`, `id_trabalhador`, `intervalos_json`, `quantidade_numeros`, `quantidade_primos`, `janela_antes`, `janela_depois`. |
| `trabalhadores` | `id_trabalhador`, `maquina`, `nucleos`, `tarefas_concluidas`, `numeros_processados`, `primos_encontrados`. |

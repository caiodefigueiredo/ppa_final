# Como executar e avaliar o projeto

Este documento explica como utilizar os fontes Python do projeto **Escalonamento paralelo adaptativo inspirado no TCP para ambiente heterogêneo**. A implementação foi construída para refletir a proposta apresentada no PDF: um mestre distribui ranges numéricos a trabalhadores, os trabalhadores contam números primos e retornam métricas de processamento, e o mestre adapta a próxima janela de trabalho conforme o comportamento observado.

## Visão geral da implementação

A implementação possui três formas principais de execução. A primeira é a execução **sequencial**, usada como referência de tempo. A segunda é a execução **paralela estática**, na qual o tamanho da janela permanece constante. A terceira é a execução **paralela adaptativa**, na qual cada trabalhador tem uma janela individual ajustada por uma regra do tipo AIMD.

| Modo | Arquivo principal | Papel na avaliação |
|---|---|---|
| Sequencial | `src/run_sequential.py` | Mede o tempo base para comparação. |
| Paralelo estático | `src/master.py --mode static` | Mede o ganho paralelo sem adaptação dinâmica. |
| Paralelo adaptativo | `src/master.py --mode adaptive` | Mede o efeito da adaptação individual por trabalhador. |
| Teste local integrado | `src/run_local_experiment.py` | Inicia mestre e trabalhadores locais automaticamente. |
| Gráficos | `src/plot_results.py` | Gera visualizações a partir do SQLite. |

## Execução rápida em uma máquina

Para validar o funcionamento localmente, entre na pasta do projeto e execute uma linha de base sequencial:

```bash
cd escalonamento_tcp_primos
python3 src/run_sequential.py --start 1000000 --end 1200000 --db results.db
```

Depois execute o modo adaptativo com três trabalhadores locais:

```bash
python3 src/run_local_experiment.py \
  --start 1000000 \
  --end 1400000 \
  --workers 3 \
  --mode adaptive \
  --worker-cores 1 \
  --port 9101 \
  --db results.db \
  --base-block-size 10000 \
  --target-time 0.4
```

Para comparar, execute o modo estático:

```bash
python3 src/run_local_experiment.py \
  --start 1000000 \
  --end 1400000 \
  --workers 3 \
  --mode static \
  --worker-cores 1 \
  --port 9102 \
  --db results.db \
  --base-block-size 10000
```

Por fim, gere os gráficos:

```bash
python3 src/plot_results.py --db results.db --out-dir plots
```

## Execução distribuída com sockets

Em cada máquina trabalhadora, execute:

```bash
python3 src/worker_node.py \
  --master-host IP_DO_MESTRE \
  --master-port 9000 \
  --worker-id worker-01 \
  --cores auto
```

No mestre, execute:

```bash
python3 src/master.py \
  --host 0.0.0.0 \
  --port 9000 \
  --expected-workers 3 \
  --start 1000000 \
  --end 5000000 \
  --mode adaptive \
  --unit-mode blocks \
  --base-block-size 10000 \
  --target-time 0.5 \
  --db results.db
```

O mestre aguardará o registro dos trabalhadores, distribuirá pacotes de trabalho e encerrará os workers quando todo o range tiver sido processado.

## Parâmetros mais importantes

| Parâmetro | Significado | Recomendação inicial |
|---|---|---|
| `--start` e `--end` | Range total de números a avaliar. | Usar ranges maiores para experimentos reais. |
| `--workers` ou `--expected-workers` | Quantidade de trabalhadores. | Testar com 1, 2, 4 e 8, se possível. |
| `--mode` | `static` ou `adaptive`. | Executar ambos para comparação. |
| `--unit-mode` | `range` ou `blocks`. | Preferir `blocks` para reduzir viés temporal. |
| `--base-block-size` | Tamanho do bloco mínimo. | Começar com 10.000 ou 50.000. |
| `--target-time` | Tempo-alvo por pacote adaptativo. | Ajustar conforme o hardware. |
| `--calibrated` | Ativa normalização por custo estimado do range. | Usar em experimentos com ranges muito altos. |
| `--worker-cores` ou `--cores` | Quantidade de processos internos por worker. | Usar `auto` em máquinas reais. |

## Relação com PCAM

| Etapa PCAM | Aplicação no código |
|---|---|
| Partitioning | O range total é dividido em blocos ou ranges menores. |
| Communication | O mestre envia tarefas por socket e recebe ACKs com tempo, quantidade processada e primos encontrados. |
| Agglomeration | A janela controla o agrupamento de blocos em pacotes maiores ou menores. |
| Mapping | O mestre decide dinamicamente qual carga enviar para cada trabalhador com base em sua resposta anterior. |

## Métricas geradas

O banco `results.db` armazena as tabelas `runs`, `tasks` e `workers`. Essas tabelas permitem calcular tempo total, throughput, quantidade de primos encontrados, evolução da janela, distribuição de carga por trabalhador e tempo médio por tarefa. Os gráficos gerados em `plots/` são úteis para a apresentação final.

| Gráfico | Arquivo | Interpretação |
|---|---|---|
| Tempo total | `plots/tempo_total.png` | Compara a duração dos modos testados. |
| Throughput | `plots/throughput.png` | Mostra números processados por segundo. |
| Evolução da janela | `plots/evolucao_janela.png` | Mostra o comportamento AIMD por trabalhador. |
| Carga por worker | `plots/carga_por_worker.png` | Mostra como a carga foi distribuída. |

## Observações para experimentos

Para que os resultados sejam mais defensáveis, evite usar ranges pequenos demais, pois o tempo de comunicação e a criação de processos podem dominar o tempo de processamento. O modo `blocks` com ordem `interleave` é o padrão recomendado, porque mistura blocos de números menores e maiores ao longo da execução, evitando que o aumento natural do custo dos testes de primalidade torne a adaptação óbvia demais.

Também é recomendável executar cada cenário mais de uma vez e comparar médias. Para a apresentação, a comparação mínima sugerida é: sequencial, paralelo estático com o mesmo número de workers e paralelo adaptativo com os mesmos workers.

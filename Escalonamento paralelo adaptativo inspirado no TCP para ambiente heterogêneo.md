# Escalonamento paralelo adaptativo inspirado no TCP para ambiente heterogêneo

Este projeto implementa uma prova de conceito em Python para o trabalho de **Programação Paralela Avançada**. O sistema usa um modelo **mestre-trabalhador** para distribuir ranges numéricos a trabalhadores remotos ou locais, que contam números primos e retornam métricas de processamento. O mestre ajusta dinamicamente o tamanho da próxima carga enviada a cada trabalhador usando uma regra inspirada em **AIMD**: aumento aditivo e diminuição multiplicativa.

A proposta implementa três modos de comparação. O modo **sequencial** processa todo o range em um único processo e serve como linha de base. O modo **paralelo estático** distribui blocos fixos aos trabalhadores. O modo **paralelo adaptativo** ajusta a janela individual de cada trabalhador conforme seu tempo de resposta, simulando uma lógica inspirada em janela, ACK e RTT do TCP.

## Estrutura

```text
src/
├── common.py              # protocolo JSON por socket e utilidades
├── prime.py               # contagem de primos em ranges
├── storage.py             # persistência SQLite das métricas
├── worker_node.py         # nó trabalhador, com multiprocessing interno
├── master.py              # mestre socket para modos static/adaptive
├── run_sequential.py      # execução sequencial de referência
├── run_local_experiment.py# orquestra mestre + workers locais para teste rápido
└── plot_results.py        # geração de gráficos a partir do SQLite
```

## Execução rápida local

Para validar o projeto em uma única máquina, execute:

```bash
cd escalonamento_tcp_primos
python3 src/run_local_experiment.py --start 1000000 --end 1200000 --workers 3 --mode adaptive --worker-cores 1 --target-time 0.4
```

Para comparar com paralelo estático:

```bash
python3 src/run_local_experiment.py --start 1000000 --end 1200000 --workers 3 --mode static --worker-cores 1
```

Para gerar a linha de base sequencial:

```bash
python3 src/run_sequential.py --start 1000000 --end 1200000 --db results.db
```

Para gerar gráficos:

```bash
python3 src/plot_results.py --db results.db --out-dir plots
```

## Execução distribuída com sockets

Em cada máquina trabalhadora, inicie um worker apontando para o IP do mestre:

```bash
python3 src/worker_node.py --master-host IP_DO_MESTRE --master-port 9000 --worker-id worker-01 --cores auto
```

No mestre, depois de iniciar os workers, execute:

```bash
python3 src/master.py --host 0.0.0.0 --port 9000 --expected-workers 3 --start 1000000 --end 2000000 --mode adaptive --db results.db
```

O mestre aguardará os trabalhadores se registrarem, distribuirá tarefas e salvará os resultados no SQLite.

## Observações metodológicas

A comunicação por socket transfere poucos dados: basicamente ranges `[inicio, fim]` e métricas. O custo computacional fica concentrado nos trabalhadores, que testam primalidade dentro do intervalo recebido. Isso permite avaliar desempenho, throughput e balanceamento sem que a rede domine o experimento.

O modo adaptativo possui duas variações importantes. Em `--unit-mode range`, a janela representa diretamente o tamanho do range. Em `--unit-mode blocks`, o range total é dividido em blocos base embaralhados ou intercalados, e a janela representa a quantidade de blocos enviados por rodada. A segunda opção reduz o viés natural causado por números maiores exigirem mais trabalho.

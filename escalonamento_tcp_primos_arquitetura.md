# Arquitetura dos fontes Python

O projeto será implementado como um sistema mestre-trabalhador inspirado em TCP para processar intervalos numéricos e contar números primos. O pacote de trabalho será representado por um ou mais ranges `[inicio, fim]`, e a janela adaptativa controlará o tamanho do range ou a quantidade de blocos base enviados ao trabalhador.

## Requisitos extraídos da proposta

| Requisito | Implementação planejada |
|---|---|
| Mestre e trabalhadores em Python 3 | `master.py` e `worker_node.py`. |
| Comunicação por socket | Protocolo JSON por TCP com mensagens terminadas por quebra de linha. |
| Armazenamento SQLite | Banco `results.db` com execuções, tarefas e métricas por trabalhador. |
| Processamento de números primos | Funções em `prime.py`, com contagem de primos em ranges. |
| Trabalhador usando múltiplos cores | Cada worker usa `multiprocessing.Pool` para dividir internamente o range recebido. |
| Modo sequencial | `run_sequential.py`, referência para tempo base. |
| Paralelo fixo | `master.py --mode static`, janela fixa por worker. |
| Paralelo adaptativo | `master.py --mode adaptive`, regra AIMD por worker. |
| Alternativa por pacotes fixos | `--unit-mode blocks`, em que a janela representa quantidade de blocos base. |
| Calibrador para ranges altos | `--calibrated`, suavizando decisões por custo estimado do range. |
| Métricas | Tempo total, throughput, primos encontrados, janela, duração por tarefa e carga por worker. |

## Estrutura do projeto

```text
escalonamento_tcp_primos/
├── README.md
├── requirements.txt
└── src/
    ├── common.py
    ├── prime.py
    ├── storage.py
    ├── worker_node.py
    ├── master.py
    ├── run_sequential.py
    ├── run_local_experiment.py
    └── plot_results.py
```

## Modos de execução

O modo sequencial processa o range completo em um único processo e serve como linha de base. O modo estático divide o range total em partes fixas enviadas aos workers, sem ajuste posterior. O modo adaptativo mantém uma janela individual por worker. Quando o worker retorna rápido em relação ao tempo-alvo, a janela aumenta de forma aditiva; quando retorna lento, a janela diminui de forma multiplicativa.

## Política AIMD

```text
se tempo_normalizado <= tempo_alvo:
    janela = min(janela + incremento, janela_maxima)
senão:
    janela = max(janela_minima, janela * fator_de_reducao)
```

Quando o calibrador estiver ativo, o tempo observado será normalizado por uma estimativa de custo baseada no valor médio do range, reduzindo o viés natural de números maiores exigirem mais processamento.

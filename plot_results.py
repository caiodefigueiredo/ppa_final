import argparse
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description='Gera gráficos simples a partir do SQLite.')
    parser.add_argument('--db', default='results.db')
    parser.add_argument('--out-dir', default='plots')
    args = parser.parse_args()

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        raise SystemExit('Instale matplotlib para gerar gráficos: pip install matplotlib')

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)

    runs = conn.execute('SELECT run_id, mode, total_seconds, throughput_numbers_per_sec FROM runs ORDER BY run_id').fetchall()
    if runs:
        labels = [f'{r[0]}-{r[1]}' for r in runs]
        times = [r[2] or 0 for r in runs]
        plt.figure(figsize=(10, 5))
        plt.bar(labels, times)
        plt.ylabel('Tempo total (s)')
        plt.xlabel('Execução')
        plt.title('Comparação de tempo total por execução')
        plt.xticks(rotation=30, ha='right')
        plt.tight_layout()
        plt.savefig(out / 'tempo_total.png', dpi=150)
        plt.close()

        throughputs = [r[3] or 0 for r in runs]
        plt.figure(figsize=(10, 5))
        plt.bar(labels, throughputs)
        plt.ylabel('Números processados por segundo')
        plt.xlabel('Execução')
        plt.title('Throughput por execução')
        plt.xticks(rotation=30, ha='right')
        plt.tight_layout()
        plt.savefig(out / 'throughput.png', dpi=150)
        plt.close()

    tasks = conn.execute('SELECT task_id, worker_id, window_before, window_after FROM tasks WHERE window_before IS NOT NULL ORDER BY task_id').fetchall()
    if tasks:
        by_worker = {}
        for task_id, worker_id, before, after in tasks:
            by_worker.setdefault(worker_id, []).append((task_id, after))
        plt.figure(figsize=(10, 5))
        for worker_id, values in by_worker.items():
            plt.plot([v[0] for v in values], [v[1] for v in values], marker='o', label=worker_id)
        plt.ylabel('Janela após ajuste')
        plt.xlabel('Tarefa')
        plt.title('Evolução da janela adaptativa por trabalhador')
        plt.legend()
        plt.tight_layout()
        plt.savefig(out / 'evolucao_janela.png', dpi=150)
        plt.close()

    worker_rows = conn.execute('SELECT run_id, worker_id, numbers_done, total_worker_seconds FROM workers ORDER BY run_id, worker_id').fetchall()
    if worker_rows:
        labels = [f'{r[0]}-{r[1]}' for r in worker_rows]
        nums = [r[2] for r in worker_rows]
        plt.figure(figsize=(10, 5))
        plt.bar(labels, nums)
        plt.ylabel('Números processados')
        plt.xlabel('Worker')
        plt.title('Distribuição de carga por trabalhador')
        plt.xticks(rotation=30, ha='right')
        plt.tight_layout()
        plt.savefig(out / 'carga_por_worker.png', dpi=150)
        plt.close()

    conn.close()
    print(f'Gráficos salvos em: {out.resolve()}')


if __name__ == '__main__':
    main()

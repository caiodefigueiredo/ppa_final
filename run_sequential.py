import argparse
import json
import time

from prime import count_primes_range
from storage import Storage


def main() -> None:
    parser = argparse.ArgumentParser(description='Execução sequencial para linha de base.')
    parser.add_argument('--start', type=int, required=True)
    parser.add_argument('--end', type=int, required=True)
    parser.add_argument('--db', default='results.db')
    args = parser.parse_args()

    storage = Storage(args.db)
    run_id = storage.create_run('sequential', args.start, args.end, trabalhadores=1, formato_trabalho='single', observacao='linha de base sequencial')
    t0 = time.perf_counter()
    primes = count_primes_range(args.start, args.end)
    elapsed = time.perf_counter() - t0
    storage.add_task(run_id, {
        'task_id': 1,
        'worker_id': 'sequential',
        'mode': 'sequential',
        'ranges_json': json.dumps([{'start': args.start, 'end': args.end}]),
        'numbers_count': max(0, args.end - args.start + 1),
        'primes_count': primes,
        'window_before': None,
        'window_after': None,
        'estimated_cost': None,
        'worker_seconds': elapsed,
        'round_trip_seconds': elapsed,
        'created_at': t0,
        'finished_at': time.perf_counter(),
    })
    storage.finish_run(run_id, elapsed, primes)
    storage.close()
    print(f'[sequencial] run_id={run_id} primos={primes} tempo={elapsed:.4f}s')


if __name__ == '__main__':
    main()

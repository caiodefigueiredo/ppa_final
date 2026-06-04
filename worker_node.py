import argparse
import os
import socket
import time
from typing import List, Tuple

from common import connect_retry, recv_json, send_json
from prime import count_primes_many_ranges


def parse_cores(value: str) -> int:
    if value == 'auto':
        return max(1, os.cpu_count() or 1)
    return max(1, int(value))


def run_worker(master_host: str, master_port: int, worker_id: str, cores: int, speed_factor: float = 1.0) -> None:
    sock = connect_retry(master_host, master_port)
    file_obj = sock.makefile('r')
    send_json(sock, {
        'type': 'register',
        'worker_id': worker_id,
        'cores': cores,
        'pid': os.getpid(),
        'host': socket.gethostname(),
        'speed_factor': speed_factor,
    })
    while True:
        msg = recv_json(file_obj)
        if msg is None:
            break
        if msg.get('type') == 'shutdown':
            send_json(sock, {'type': 'bye', 'worker_id': worker_id})
            break
        if msg.get('type') != 'task':
            continue
        task_id = msg['task_id']
        ranges: List[Tuple[int, int]] = [(int(r['start']), int(r['end'])) for r in msg['ranges']]
        t0 = time.perf_counter()
        primes = count_primes_many_ranges(ranges, cores=cores)
        if speed_factor > 1.0:
            # Recurso opcional para simular heterogeneidade em testes locais.
            time.sleep((speed_factor - 1.0) * 0.01)
        elapsed = time.perf_counter() - t0
        numbers_count = sum(max(0, b - a + 1) for a, b in ranges)
        send_json(sock, {
            'type': 'result',
            'task_id': task_id,
            'worker_id': worker_id,
            'primes_count': primes,
            'numbers_count': numbers_count,
            'worker_seconds': elapsed,
        })
    try:
        sock.close()
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description='Worker para contagem de primos via socket.')
    parser.add_argument('--master-host', required=True)
    parser.add_argument('--master-port', type=int, default=9000)
    parser.add_argument('--worker-id', default=None)
    parser.add_argument('--cores', default='auto', help='auto ou número inteiro')
    parser.add_argument('--speed-factor', type=float, default=1.0, help='Opcional para simular trabalhador mais lento em testes locais')
    args = parser.parse_args()
    worker_id = args.worker_id or f'{socket.gethostname()}-{os.getpid()}'
    run_worker(args.master_host, args.master_port, worker_id, parse_cores(args.cores), args.speed_factor)


if __name__ == '__main__':
    main()

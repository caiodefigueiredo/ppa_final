import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def wait_process(proc: subprocess.Popen) -> int:
    return proc.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description='Executa mestre e workers locais para validação rápida.')
    parser.add_argument('--start', type=int, required=True)
    parser.add_argument('--end', type=int, required=True)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--mode', choices=['static', 'adaptive'], default='adaptive')
    parser.add_argument('--unit-mode', choices=['range', 'blocks'], default='blocks')
    parser.add_argument('--worker-cores', default='1')
    parser.add_argument('--port', type=int, default=9000)
    parser.add_argument('--db', default='results.db')
    parser.add_argument('--base-block-size', type=int, default=10000)
    parser.add_argument('--target-time', type=float, default=0.5)
    parser.add_argument('--calibrated', action='store_true')
    args = parser.parse_args()

    src_dir = Path(__file__).resolve().parent
    master_cmd = [
        sys.executable, str(src_dir / 'master.py'),
        '--host', '127.0.0.1', '--port', str(args.port), '--expected-workers', str(args.workers),
        '--start', str(args.start), '--end', str(args.end), '--mode', args.mode,
        '--unit-mode', args.unit_mode, '--base-block-size', str(args.base_block_size),
        '--target-time', str(args.target_time), '--db', args.db,
    ]
    if args.calibrated:
        master_cmd.append('--calibrated')

    master = subprocess.Popen(master_cmd)
    workers = []
    try:
        time.sleep(0.8)
        for i in range(args.workers):
            # Simula pequena heterogeneidade local: workers com fatores diferentes.
            speed_factor = 1.0 + (i % 3) * 0.6
            cmd = [
                sys.executable, str(src_dir / 'worker_node.py'), '--master-host', '127.0.0.1', '--master-port', str(args.port),
                '--worker-id', f'local-worker-{i+1}', '--cores', args.worker_cores, '--speed-factor', str(speed_factor),
            ]
            workers.append(subprocess.Popen(cmd))
        rc = master.wait()
        if rc != 0:
            raise SystemExit(rc)
    finally:
        for proc in workers:
            if proc.poll() is None:
                proc.terminate()
        if master.poll() is None:
            master.terminate()


if __name__ == '__main__':
    main()

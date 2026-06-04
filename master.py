import argparse
import json
import random
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from common import RangeBlock, estimate_range_cost, interleave_low_high, make_ordered_blocks, recv_json, send_json
from storage import Storage


@dataclass
class WorkerConn:
    worker_id: str
    sock: socket.socket
    file_obj: object
    host: str
    cores: int
    speed_factor: float = 1.0
    busy: bool = False
    current_task_id: Optional[int] = None
    last_sent_at: float = 0.0
    window: float = 1.0
    tasks_done: int = 0
    numbers_done: int = 0
    primes_done: int = 0


@dataclass
class TaskMeta:
    task_id: int
    worker_id: str
    ranges: List[RangeBlock]
    mode: str
    window_before: float
    estimated_cost: float
    created_at: float


class Master:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.storage = Storage(args.db)
        self.run_id = self.storage.create_run(args.mode, args.start, args.end, args.expected_workers, args.unit_mode, notes='execução mestre-trabalhador por socket')
        self.workers: Dict[str, WorkerConn] = {}
        self.pending_blocks: List[RangeBlock] = []
        self.next_range_start = args.start
        self.task_id = 0
        self.tasks: Dict[int, TaskMeta] = {}
        self.total_primes = 0
        self.total_numbers_done = 0
        self.lock = threading.Lock()
        self.done_event = threading.Event()

    def prepare_blocks(self) -> None:
        if self.args.unit_mode == 'blocks':
            blocks = make_ordered_blocks(self.args.start, self.args.end, self.args.base_block_size)
            if self.args.block_order == 'shuffle':
                rnd = random.Random(self.args.seed)
                rnd.shuffle(blocks)
            elif self.args.block_order == 'interleave':
                blocks = interleave_low_high(blocks)
            self.pending_blocks = blocks

    def start_server(self) -> socket.socket:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.args.host, self.args.port))
        server.listen()
        return server

    def accept_workers(self, server: socket.socket) -> None:
        print(f'[mestre] aguardando {self.args.expected_workers} workers em {self.args.host}:{self.args.port}...')
        while len(self.workers) < self.args.expected_workers:
            sock, addr = server.accept()
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            file_obj = sock.makefile('r')
            msg = recv_json(file_obj)
            if not msg or msg.get('type') != 'register':
                sock.close()
                continue
            worker_id = msg['worker_id']
            worker = WorkerConn(
                worker_id=worker_id,
                sock=sock,
                file_obj=file_obj,
                host=msg.get('host', addr[0]),
                cores=int(msg.get('cores', 1)),
                speed_factor=float(msg.get('speed_factor', 1.0)),
                window=float(self.args.initial_window),
            )
            self.workers[worker_id] = worker
            self.storage.add_worker(self.run_id, worker_id, worker.host, worker.cores)
            print(f'[mestre] worker registrado: {worker_id}, host={worker.host}, cores={worker.cores}')
            t = threading.Thread(target=self.listen_worker, args=(worker,), daemon=True)
            t.start()

    def has_more_work(self) -> bool:
        if self.args.unit_mode == 'blocks':
            return bool(self.pending_blocks)
        return self.next_range_start <= self.args.end

    def allocate_ranges(self, worker: WorkerConn) -> List[RangeBlock]:
        if self.args.unit_mode == 'blocks':
            n_blocks = max(1, int(round(worker.window)))
            allocated = self.pending_blocks[:n_blocks]
            self.pending_blocks = self.pending_blocks[n_blocks:]
            return allocated
        size = max(1, int(round(worker.window)))
        start = self.next_range_start
        end = min(self.args.end, start + size - 1)
        self.next_range_start = end + 1
        return [RangeBlock(start, end)]

    def dispatch_if_possible(self, worker: WorkerConn) -> None:
        with self.lock:
            if worker.busy or not self.has_more_work():
                return
            ranges = self.allocate_ranges(worker)
            if not ranges:
                return
            self.task_id += 1
            task_id = self.task_id
            estimated = sum(estimate_range_cost(r.start, r.end) for r in ranges)
            meta = TaskMeta(task_id, worker.worker_id, ranges, self.args.mode, worker.window, estimated, time.perf_counter())
            self.tasks[task_id] = meta
            worker.busy = True
            worker.current_task_id = task_id
            worker.last_sent_at = meta.created_at
            message = {'type': 'task', 'task_id': task_id, 'mode': self.args.mode, 'ranges': [r.to_dict() for r in ranges]}
        send_json(worker.sock, message)

    def adjust_window(self, worker: WorkerConn, worker_seconds: float, meta: TaskMeta) -> None:
        if self.args.mode == 'static':
            return
        decision_time = worker_seconds
        if self.args.calibrated and meta.estimated_cost > 0:
            # Normaliza em relação ao custo estimado. A constante inicial é calibrada
            # de forma simples após a primeira execução por worker.
            units_per_second = meta.estimated_cost / max(worker_seconds, 1e-9)
            reference = getattr(worker, 'reference_units_per_second', None)
            if reference is None:
                setattr(worker, 'reference_units_per_second', units_per_second)
                decision_time = self.args.target_time
            else:
                decision_time = self.args.target_time * (reference / max(units_per_second, 1e-9))
        if decision_time <= self.args.target_time:
            worker.window = min(self.args.max_window, worker.window + self.args.additive_step)
        else:
            worker.window = max(self.args.min_window, worker.window * self.args.decrease_factor)

    def listen_worker(self, worker: WorkerConn) -> None:
        while not self.done_event.is_set():
            msg = recv_json(worker.file_obj)
            if msg is None:
                break
            if msg.get('type') == 'result':
                self.handle_result(worker, msg)
                self.dispatch_if_possible(worker)
                self.check_done()

    def handle_result(self, worker: WorkerConn, msg: dict) -> None:
        finished = time.perf_counter()
        with self.lock:
            task_id = int(msg['task_id'])
            meta = self.tasks.pop(task_id)
            worker_seconds = float(msg['worker_seconds'])
            round_trip = finished - meta.created_at
            primes = int(msg['primes_count'])
            numbers = int(msg['numbers_count'])
            self.total_primes += primes
            self.total_numbers_done += numbers
            worker.busy = False
            worker.current_task_id = None
            worker.tasks_done += 1
            worker.numbers_done += numbers
            worker.primes_done += primes
            self.adjust_window(worker, worker_seconds, meta)
            self.storage.add_task(self.run_id, {
                'task_id': task_id,
                'worker_id': worker.worker_id,
                'mode': self.args.mode,
                'ranges_json': json.dumps([r.to_dict() for r in meta.ranges]),
                'numbers_count': numbers,
                'primes_count': primes,
                'window_before': meta.window_before,
                'window_after': worker.window,
                'estimated_cost': meta.estimated_cost,
                'worker_seconds': worker_seconds,
                'round_trip_seconds': round_trip,
                'created_at': meta.created_at,
                'finished_at': finished,
            })
            print(f"[mestre] task={task_id} worker={worker.worker_id} nums={numbers} primes={primes} tempo={worker_seconds:.4f}s janela {meta.window_before:.1f}->{worker.window:.1f}")

    def check_done(self) -> None:
        with self.lock:
            busy = any(w.busy for w in self.workers.values())
            if not self.has_more_work() and not busy and not self.tasks:
                self.done_event.set()

    def run(self) -> None:
        self.prepare_blocks()
        server = self.start_server()
        self.accept_workers(server)
        start = time.perf_counter()
        for worker in list(self.workers.values()):
            self.dispatch_if_possible(worker)
        self.done_event.wait()
        total_seconds = time.perf_counter() - start
        self.storage.finish_run(self.run_id, total_seconds, self.total_primes)
        for worker in self.workers.values():
            try:
                send_json(worker.sock, {'type': 'shutdown'})
                worker.sock.close()
            except OSError:
                pass
        server.close()
        print(f'[mestre] execução finalizada. run_id={self.run_id} total_primos={self.total_primes} tempo={total_seconds:.4f}s números={self.total_numbers_done}')
        self.storage.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='Mestre para escalonamento paralelo de ranges de primos.')
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--port', type=int, default=9000)
    p.add_argument('--expected-workers', type=int, required=True)
    p.add_argument('--start', type=int, required=True)
    p.add_argument('--end', type=int, required=True)
    p.add_argument('--mode', choices=['static', 'adaptive'], default='adaptive')
    p.add_argument('--unit-mode', choices=['range', 'blocks'], default='blocks')
    p.add_argument('--base-block-size', type=int, default=10000)
    p.add_argument('--block-order', choices=['ordered', 'shuffle', 'interleave'], default='interleave')
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--initial-window', type=float, default=2.0, help='range size em unit-mode=range ou quantidade de blocos em unit-mode=blocks')
    p.add_argument('--min-window', type=float, default=1.0)
    p.add_argument('--max-window', type=float, default=64.0)
    p.add_argument('--additive-step', type=float, default=1.0)
    p.add_argument('--decrease-factor', type=float, default=0.5)
    p.add_argument('--target-time', type=float, default=0.5)
    p.add_argument('--calibrated', action='store_true')
    p.add_argument('--db', default='results.db')
    return p


def main() -> None:
    args = build_parser().parse_args()
    if args.end < args.start:
        raise SystemExit('--end deve ser maior ou igual a --start')
    Master(args).run()


if __name__ == '__main__':
    main()

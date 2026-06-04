from pathlib import Path

BASE = Path('/home/ubuntu/escalonamento_tcp_primos')
SRC = BASE / 'src'
SRC.mkdir(parents=True, exist_ok=True)

files = {}

files['README.md'] = r'''# Escalonamento paralelo adaptativo inspirado no TCP para ambiente heterogêneo

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
'''

files['requirements.txt'] = r'''# O projeto usa somente bibliotecas padrão para execução.
# matplotlib é opcional para geração de gráficos.
matplotlib>=3.7
'''

files['src/common.py'] = r'''import json
import socket
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

ENCODING = 'utf-8'


def now() -> float:
    return time.perf_counter()


def send_json(sock: socket.socket, message: Dict[str, Any]) -> None:
    data = json.dumps(message, separators=(',', ':')).encode(ENCODING) + b'\n'
    sock.sendall(data)


def recv_json(file_obj) -> Optional[Dict[str, Any]]:
    line = file_obj.readline()
    if not line:
        return None
    if isinstance(line, bytes):
        line = line.decode(ENCODING)
    return json.loads(line)


def connect_retry(host: str, port: int, retries: int = 60, delay: float = 0.5) -> socket.socket:
    last_error = None
    for _ in range(retries):
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return sock
        except OSError as exc:
            last_error = exc
            time.sleep(delay)
    raise ConnectionError(f'Não foi possível conectar a {host}:{port}: {last_error}')


@dataclass
class RangeBlock:
    start: int
    end: int

    @property
    def size(self) -> int:
        return max(0, self.end - self.start + 1)

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


def estimate_range_cost(start: int, end: int) -> float:
    """Estimativa simples de custo para normalização.

    Para teste por divisão até sqrt(n), intervalos com números maiores tendem a
    custar mais. A função não precisa ser perfeita; ela serve para suavizar a
    decisão adaptativa e reduzir o viés temporal de ranges crescentes.
    """
    if end < start:
        return 0.0
    mid = (start + end) / 2.0
    return (end - start + 1) * max(mid, 1.0) ** 0.5


def make_ordered_blocks(start: int, end: int, block_size: int) -> List[RangeBlock]:
    blocks: List[RangeBlock] = []
    cur = start
    while cur <= end:
        b_end = min(end, cur + block_size - 1)
        blocks.append(RangeBlock(cur, b_end))
        cur = b_end + 1
    return blocks


def interleave_low_high(blocks: List[RangeBlock]) -> List[RangeBlock]:
    result: List[RangeBlock] = []
    lo, hi = 0, len(blocks) - 1
    while lo <= hi:
        result.append(blocks[lo])
        if lo != hi:
            result.append(blocks[hi])
        lo += 1
        hi -= 1
    return result
'''

files['src/prime.py'] = r'''import math
from multiprocessing import Pool
from typing import Iterable, List, Sequence, Tuple


def is_prime(n: int) -> bool:
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    limit = math.isqrt(n)
    d = 3
    while d <= limit:
        if n % d == 0:
            return False
        d += 2
    return True


def count_primes_range(start: int, end: int) -> int:
    if end < start:
        return 0
    count = 0
    for n in range(start, end + 1):
        if is_prime(n):
            count += 1
    return count


def split_range(start: int, end: int, parts: int) -> List[Tuple[int, int]]:
    total = max(0, end - start + 1)
    if total == 0:
        return []
    parts = max(1, min(parts, total))
    base = total // parts
    rem = total % parts
    chunks: List[Tuple[int, int]] = []
    cur = start
    for i in range(parts):
        size = base + (1 if i < rem else 0)
        c_end = cur + size - 1
        chunks.append((cur, c_end))
        cur = c_end + 1
    return chunks


def _count_tuple(args: Tuple[int, int]) -> int:
    return count_primes_range(args[0], args[1])


def count_primes_many_ranges(ranges: Sequence[Tuple[int, int]], cores: int = 1) -> int:
    if not ranges:
        return 0
    if cores <= 1:
        return sum(count_primes_range(a, b) for a, b in ranges)
    # A granularidade é feita no nível dos ranges recebidos do mestre.
    # Caso haja poucos ranges, subdividimos cada um para usar os cores locais.
    chunks: List[Tuple[int, int]] = []
    for start, end in ranges:
        chunks.extend(split_range(start, end, max(1, cores)))
    with Pool(processes=cores) as pool:
        return sum(pool.map(_count_tuple, chunks))
'''

files['src/storage.py'] = r"""import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

SCHEMA = '''
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    start_value INTEGER NOT NULL,
    end_value INTEGER NOT NULL,
    expected_workers INTEGER,
    unit_mode TEXT,
    started_at REAL NOT NULL,
    finished_at REAL,
    total_seconds REAL,
    total_primes INTEGER DEFAULT 0,
    total_numbers INTEGER DEFAULT 0,
    throughput_numbers_per_sec REAL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    worker_id TEXT,
    mode TEXT NOT NULL,
    ranges_json TEXT NOT NULL,
    numbers_count INTEGER NOT NULL,
    primes_count INTEGER NOT NULL,
    window_before REAL,
    window_after REAL,
    estimated_cost REAL,
    worker_seconds REAL NOT NULL,
    round_trip_seconds REAL,
    created_at REAL NOT NULL,
    finished_at REAL NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS workers (
    run_id INTEGER NOT NULL,
    worker_id TEXT NOT NULL,
    host TEXT,
    cores INTEGER,
    registered_at REAL,
    tasks_done INTEGER DEFAULT 0,
    numbers_done INTEGER DEFAULT 0,
    primes_done INTEGER DEFAULT 0,
    total_worker_seconds REAL DEFAULT 0,
    PRIMARY KEY(run_id, worker_id),
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
'''


class Storage:
    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path))
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def create_run(self, mode: str, start_value: int, end_value: int, expected_workers: Optional[int], unit_mode: str, notes: str = '') -> int:
        cur = self.conn.execute(
            'INSERT INTO runs(mode,start_value,end_value,expected_workers,unit_mode,started_at,notes,total_numbers) VALUES(?,?,?,?,?,?,?,?)',
            (mode, start_value, end_value, expected_workers, unit_mode, time.time(), notes, max(0, end_value - start_value + 1)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, total_seconds: float, total_primes: int) -> None:
        total_numbers = self.conn.execute('SELECT total_numbers FROM runs WHERE run_id=?', (run_id,)).fetchone()[0]
        throughput = total_numbers / total_seconds if total_seconds > 0 else 0
        self.conn.execute(
            'UPDATE runs SET finished_at=?, total_seconds=?, total_primes=?, throughput_numbers_per_sec=? WHERE run_id=?',
            (time.time(), total_seconds, total_primes, throughput, run_id),
        )
        self.conn.commit()

    def add_worker(self, run_id: int, worker_id: str, host: str, cores: int) -> None:
        self.conn.execute(
            'INSERT OR REPLACE INTO workers(run_id,worker_id,host,cores,registered_at) VALUES(?,?,?,?,?)',
            (run_id, worker_id, host, cores, time.time()),
        )
        self.conn.commit()

    def add_task(self, run_id: int, task: Dict[str, Any]) -> None:
        self.conn.execute(
            '''INSERT OR REPLACE INTO tasks(task_id,run_id,worker_id,mode,ranges_json,numbers_count,primes_count,
               window_before,window_after,estimated_cost,worker_seconds,round_trip_seconds,created_at,finished_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                task['task_id'], run_id, task.get('worker_id'), task['mode'], task['ranges_json'], task['numbers_count'],
                task['primes_count'], task.get('window_before'), task.get('window_after'), task.get('estimated_cost'),
                task['worker_seconds'], task.get('round_trip_seconds'), task['created_at'], task['finished_at'],
            ),
        )
        if task.get('worker_id'):
            self.conn.execute(
                '''UPDATE workers SET tasks_done=tasks_done+1, numbers_done=numbers_done+?, primes_done=primes_done+?,
                   total_worker_seconds=total_worker_seconds+? WHERE run_id=? AND worker_id=?''',
                (task['numbers_count'], task['primes_count'], task['worker_seconds'], run_id, task['worker_id']),
            )
        self.conn.commit()
"""

files['src/worker_node.py'] = r'''import argparse
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
'''

files['src/master.py'] = r'''import argparse
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
'''

files['src/run_sequential.py'] = r'''import argparse
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
    run_id = storage.create_run('sequential', args.start, args.end, expected_workers=1, unit_mode='single', notes='linha de base sequencial')
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
'''

files['src/run_local_experiment.py'] = r'''import argparse
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
'''

files['src/plot_results.py'] = r'''import argparse
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
'''

files['src/__init__.py'] = ''

for rel, content in files.items():
    path = BASE / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')

print(f'Projeto criado em {BASE}')

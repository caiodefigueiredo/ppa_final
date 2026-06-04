import sqlite3
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
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
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

import json
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

import math
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

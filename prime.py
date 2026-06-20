from math import isqrt
from multiprocessing import Pool
from typing import List, Tuple


def eh_primo(numero: int) -> bool:
    if numero < 2:
        return False
    if numero == 2:
        return True
    if numero % 2 == 0:
        return False
    limite = isqrt(numero)
    divisor = 3
    while divisor <= limite:
        if numero % divisor == 0:
            return False
        divisor += 2
    return True


def contar_primos_intervalo(inicio: int, fim: int) -> int:
    if fim < inicio:
        return 0
    total = 0
    for numero in range(inicio, fim + 1):
        if eh_primo(numero):
            total += 1
    return total


def dividir_intervalo(inicio: int, fim: int, partes: int) -> List[Tuple[int, int]]:
    partes = max(1, partes)
    tamanho = max(1, fim - inicio + 1)
    passo = max(1, tamanho // partes)
    intervalos: List[Tuple[int, int]] = []
    atual = inicio
    while atual <= fim:
        fim_parte = min(fim, atual + passo - 1)
        intervalos.append((atual, fim_parte))
        atual = fim_parte + 1
    return intervalos


def _contar_tupla(intervalo: Tuple[int, int]) -> int:
    return contar_primos_intervalo(intervalo[0], intervalo[1])


def contar_primos_varios_intervalos(intervalos: List[Tuple[int, int]], nucleos: int = 1) -> int:
    if not intervalos:
        return 0
    if nucleos <= 1:
        return sum(contar_primos_intervalo(inicio, fim) for inicio, fim in intervalos)
    subintervalos: List[Tuple[int, int]] = []
    for inicio, fim in intervalos:
        subintervalos.extend(dividir_intervalo(inicio, fim, nucleos))
    with Pool(processes=nucleos) as pool:
        return sum(pool.map(_contar_tupla, subintervalos))

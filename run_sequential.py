import argparse
import json
import time
from math import isqrt

from armazenamento import Armazenamento


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


def main() -> None:
    parser = argparse.ArgumentParser(description='Execução sequencial para linha de base.')
    parser.add_argument('--inicio', '--start', dest='inicio', type=int, required=True)
    parser.add_argument('--fim', '--end', dest='fim', type=int, required=True)
    parser.add_argument('--banco', '--db', dest='banco', default='resultados.db')
    argumentos = parser.parse_args()

    armazenamento = Armazenamento(argumentos.banco)
    id_execucao = armazenamento.criar_execucao('sequencial', argumentos.inicio, argumentos.fim, trabalhadores_esperados=1, modo_unidade='unico', observacoes='linha de base sequencial')
    inicio_tempo = time.perf_counter()
    primos = contar_primos_intervalo(argumentos.inicio, argumentos.fim)
    tempo_decorrido = time.perf_counter() - inicio_tempo
    armazenamento.adicionar_tarefa(id_execucao, {
        'id_tarefa': 1,
        'id_trabalhador': 'sequencial',
        'modo': 'sequencial',
        'intervalos_json': json.dumps([{'inicio': argumentos.inicio, 'fim': argumentos.fim}]),
        'quantidade_numeros': max(0, argumentos.fim - argumentos.inicio + 1),
        'quantidade_primos': primos,
        'janela_antes': None,
        'janela_depois': None,
        'custo_estimado': None,
        'segundos_trabalhador': tempo_decorrido,
        'segundos_ida_volta': tempo_decorrido,
        'criado_em': inicio_tempo,
        'fim_em': time.perf_counter(),
    })
    armazenamento.finalizar_execucao(id_execucao, tempo_decorrido, primos)
    armazenamento.fechar()
    print(f'[sequencial] id_execucao={id_execucao} primos={primos} tempo={tempo_decorrido:.4f}s')


if __name__ == '__main__':
    main()

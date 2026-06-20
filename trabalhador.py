import argparse
import os
import socket
import threading
import time
from math import isqrt
from multiprocessing import Pool
from typing import List, Tuple

from funcoes_trabalhador import conectar_com_tentativas, enviar_json, receber_json


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


def detectar_nucleos_trabalhador(valor: str = 'auto') -> int:
    if valor == 'auto':
        return max(1, os.cpu_count() or 1)
    return max(1, int(valor))


def enviar_com_trava(conexao: socket.socket, trava_envio: threading.Lock, mensagem: dict) -> None:
    with trava_envio:
        enviar_json(conexao, mensagem)


def enviar_heartbeats(conexao: socket.socket, id_trabalhador: str, intervalo: float, evento_parar: threading.Event, trava_envio: threading.Lock) -> None:
    while not evento_parar.wait(intervalo):
        try:
            enviar_com_trava(conexao, trava_envio, {
                'tipo': 'heartbeat',
                'id_trabalhador': id_trabalhador,
                'enviado_em': time.time(),
            })
        except OSError:
            evento_parar.set()
            break


def executar_trabalhador(endereco_mestre: str, porta_mestre: int, id_trabalhador: str, nucleos: int, intervalo_heartbeat: float) -> None:
    conexao = conectar_com_tentativas(endereco_mestre, porta_mestre)
    arquivo_conexao = conexao.makefile('r')
    trava_envio = threading.Lock()
    evento_parar = threading.Event()
    enviar_com_trava(conexao, trava_envio, {
        'tipo': 'registro',
        'id_trabalhador': id_trabalhador,
        'nucleos': nucleos,
        'pid': os.getpid(),
        'maquina': socket.gethostname(),
    })
    thread_heartbeat = threading.Thread(
        target=enviar_heartbeats,
        args=(conexao, id_trabalhador, intervalo_heartbeat, evento_parar, trava_envio),
        daemon=True,
    )
    thread_heartbeat.start()
    while True:
        mensagem = receber_json(arquivo_conexao)
        if mensagem is None:
            break
        if mensagem.get('tipo') == 'encerrar':
            try:
                enviar_com_trava(conexao, trava_envio, {'tipo': 'tchau', 'id_trabalhador': id_trabalhador})
            except OSError:
                pass
            break
        if mensagem.get('tipo') != 'tarefa':
            continue
        id_tarefa = mensagem['id_tarefa']
        intervalos: List[Tuple[int, int]] = [(int(r['inicio']), int(r['fim'])) for r in mensagem['intervalos']]
        inicio_tempo = time.perf_counter()
        primos = contar_primos_varios_intervalos(intervalos, nucleos=nucleos)
        tempo_decorrido = time.perf_counter() - inicio_tempo
        quantidade_numeros = sum(max(0, fim - inicio + 1) for inicio, fim in intervalos)
        try:
            enviar_com_trava(conexao, trava_envio, {
                'tipo': 'resultado',
                'id_tarefa': id_tarefa,
                'id_trabalhador': id_trabalhador,
                'quantidade_primos': primos,
                'quantidade_numeros': quantidade_numeros,
                'segundos_trabalhador': tempo_decorrido,
            })
        except OSError:
            break
    evento_parar.set()
    thread_heartbeat.join(timeout=2.0)
    try:
        conexao.close()
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description='Trabalhador para contagem de primos via socket.')
    parser.add_argument('--endereco-mestre', '--master-host', dest='endereco_mestre', required=True)
    parser.add_argument('--porta-mestre', '--master-port', dest='porta_mestre', type=int, default=9000)
    parser.add_argument('--id-trabalhador', '--worker-id', dest='id_trabalhador', default=None)
    parser.add_argument('--nucleos', '--cores', dest='nucleos', default='auto')
    parser.add_argument('--intervalo-heartbeat', dest='intervalo_heartbeat', type=float, default=60.0)
    argumentos = parser.parse_args()
    if argumentos.intervalo_heartbeat <= 0:
        raise SystemExit('--intervalo-heartbeat deve ser maior que zero')
    id_trabalhador = argumentos.id_trabalhador or f'{socket.gethostname()}-{os.getpid()}'
    nucleos_trabalhador = detectar_nucleos_trabalhador(argumentos.nucleos)
    executar_trabalhador(argumentos.endereco_mestre, argumentos.porta_mestre, id_trabalhador, nucleos_trabalhador, argumentos.intervalo_heartbeat)


if __name__ == '__main__':
    main()

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJETO = Path('/home/ubuntu/escalonamento_tcp_primos')
SRC = PROJETO / 'src'
PORTA = 9203
BANCO = '/tmp/teste_heartbeat.db'


def enviar_json(conexao: socket.socket, mensagem: dict) -> None:
    conexao.sendall((json.dumps(mensagem, ensure_ascii=False) + '\n').encode('utf-8'))


def receber_linha(conexao: socket.socket):
    arquivo = conexao.makefile('r')
    linha = arquivo.readline()
    if not linha:
        return None
    return json.loads(linha)


def trabalhador_sem_heartbeat() -> None:
    conexao = socket.create_connection(('127.0.0.1', PORTA), timeout=10)
    enviar_json(conexao, {
        'tipo': 'registro',
        'id_trabalhador': 'trabalhador-sem-heartbeat',
        'nucleos': 1,
        'pid': os.getpid(),
        'maquina': socket.gethostname(),
    })
    mensagem = receber_linha(conexao)
    if mensagem is None or mensagem.get('tipo') != 'tarefa':
        raise SystemExit('trabalhador sem heartbeat não recebeu tarefa')
    time.sleep(8)
    conexao.close()


def principal() -> int:
    try:
        os.remove(BANCO)
    except FileNotFoundError:
        pass

    mestre = subprocess.Popen([
        sys.executable, str(SRC / 'mestre.py'),
        '--endereco', '127.0.0.1',
        '--porta', str(PORTA),
        '--max-trabalhadores', '2',
        '--min-trabalhadores', '2',
        '--tempo-espera-trabalhadores', '0',
        '--timeout-heartbeat', '3',
        '--intervalo-monitoramento-heartbeat', '1',
        '--inicio', '1',
        '--fim', '5000',
        '--modo', 'adaptativo',
        '--modo-unidade', 'blocos',
        '--tamanho-bloco-base', '100',
        '--tempo-alvo', '0.2',
        '--banco', BANCO,
    ], cwd=str(PROJETO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    time.sleep(0.6)
    ruim = subprocess.Popen([sys.executable, __file__, 'ruim'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(0.2)
    bom = subprocess.Popen([
        sys.executable, str(SRC / 'trabalhador.py'),
        '--endereco-mestre', '127.0.0.1',
        '--porta-mestre', str(PORTA),
        '--id-trabalhador', 'trabalhador-saudavel',
        '--intervalo-heartbeat', '1',
        '--nucleos', '1',
    ], cwd=str(PROJETO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    try:
        saida_mestre, _ = mestre.communicate(timeout=30)
    finally:
        for processo in (ruim, bom, mestre):
            if processo.poll() is None:
                processo.terminate()
    saida_ruim = ruim.communicate(timeout=5)[0] if ruim.poll() is not None else ''
    saida_bom = bom.communicate(timeout=5)[0] if bom.poll() is not None else ''

    print('--- SAÍDA DO MESTRE ---')
    print(saida_mestre)
    if saida_ruim.strip():
        print('--- SAÍDA DO TRABALHADOR SEM HEARTBEAT ---')
        print(saida_ruim)
    if saida_bom.strip():
        print('--- SAÍDA DO TRABALHADOR SAUDÁVEL ---')
        print(saida_bom)

    if mestre.returncode != 0:
        print(f'ERRO: mestre terminou com código {mestre.returncode}')
        return 1
    if 'total_primos=669' not in saida_mestre:
        print('ERRO: total esperado de 669 primos não foi encontrado.')
        return 1
    if 'devolvida para pendência' not in saida_mestre:
        print('ERRO: mensagem de devolução de tarefa pendente não foi encontrada.')
        return 1
    print('OK: recuperação por heartbeat validada com total_primos=669.')
    return 0


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'ruim':
        trabalhador_sem_heartbeat()
    else:
        raise SystemExit(principal())

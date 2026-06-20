import argparse
import subprocess
import sys
import time
from pathlib import Path


def normalizar_modo(modo: str) -> str:
    return {'static': 'estatico', 'adaptive': 'adaptativo'}.get(modo, modo)


def main() -> None:
    parser = argparse.ArgumentParser(description='Executa mestre e trabalhadores locais para validação rápida.')
    parser.add_argument('--inicio', '--start', dest='inicio', type=int, required=True)
    parser.add_argument('--fim', '--end', dest='fim', type=int, required=True)
    parser.add_argument('--trabalhadores', '--workers', dest='trabalhadores', type=int, default=3)
    parser.add_argument('--modo', '--mode', dest='modo', choices=['estatico', 'adaptativo', 'static', 'adaptive'], default='adaptativo')
    parser.add_argument('--nucleos-trabalhador', '--worker-cores', dest='nucleos_trabalhador', default=None, help='opcional: sobrescreve localmente os núcleos usados por cada trabalhador; se omitido, cada worker usa auto')
    parser.add_argument('--porta', '--port', dest='porta', type=int, default=9000)
    parser.add_argument('--banco', '--db', dest='banco', default='resultados.db')
    parser.add_argument('--tamanho-bloco-base', '--base-block-size', dest='tamanho_bloco_base', type=int, default=10000)
    parser.add_argument('--tempo-alvo', '--target-time', dest='tempo_alvo', type=float, default=0.5)
    parser.add_argument('--calibrado', '--calibrated', dest='calibrado', action='store_true')
    argumentos = parser.parse_args()

    diretorio_src = Path(__file__).resolve().parent
    modo = normalizar_modo(argumentos.modo)
    comando_mestre = [
        sys.executable, str(diretorio_src / 'mestre.py'),
        '--endereco', '127.0.0.1', '--porta', str(argumentos.porta), '--max-trabalhadores', str(argumentos.trabalhadores),
        '--inicio', str(argumentos.inicio), '--fim', str(argumentos.fim), '--modo', modo,
        '--tamanho-bloco-base', str(argumentos.tamanho_bloco_base),
        '--tempo-alvo', str(argumentos.tempo_alvo), '--banco', argumentos.banco,
    ]
    if argumentos.calibrado:
        comando_mestre.append('--calibrado')

    mestre = subprocess.Popen(comando_mestre)
    trabalhadores = []
    try:
        time.sleep(0.8)
        for indice in range(argumentos.trabalhadores):
            comando_trabalhador = [
                sys.executable, str(diretorio_src / 'trabalhador.py'), '--endereco-mestre', '127.0.0.1', '--porta-mestre', str(argumentos.porta),
                '--id-trabalhador', f'trabalhador-local-{indice+1}',
            ]
            if argumentos.nucleos_trabalhador is not None:
                comando_trabalhador.extend(['--nucleos', argumentos.nucleos_trabalhador])
            trabalhadores.append(subprocess.Popen(comando_trabalhador))
        codigo_retorno = mestre.wait()
        if codigo_retorno != 0:
            raise SystemExit(codigo_retorno)
    finally:
        for processo in trabalhadores:
            if processo.poll() is None:
                processo.terminate()
        if mestre.poll() is None:
            mestre.terminate()


if __name__ == '__main__':
    main()

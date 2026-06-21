import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
SCRIPTS = [
    RAIZ / 'src' / 'mestre.py',
    RAIZ / 'src' / 'trabalhador.py',
    RAIZ / 'src' / 'run_local_experiment.py',
    RAIZ / 'src' / 'run_sequential.py',
    RAIZ / 'src' / 'plot_results.py',
]
PROIBIDOS = [
    '--calibrado', '--calibrated', '--start', '--end', '--workers', '--mode',
    '--worker-cores', '--db', '--base-block-size', '--target-time',
    '--master-host', '--master-port', '--worker-id', '--cores', '--out-dir',
]

def contem_opcao_completa(texto: str, opcao: str) -> bool:
    padrao = re.compile(r'(?<![\w-])' + re.escape(opcao) + r'(?![\w-])')
    return bool(padrao.search(texto))

for script in SCRIPTS:
    resultado = subprocess.run([sys.executable, str(script), '--help'], text=True, capture_output=True, check=False)
    if resultado.returncode != 0:
        print(f'Falha ao obter ajuda de {script}: {resultado.stderr}', file=sys.stderr)
        raise SystemExit(1)
    encontrados = [item for item in PROIBIDOS if contem_opcao_completa(resultado.stdout, item)]
    if encontrados:
        print(f'Aliases ou opções proibidas em {script}: {encontrados}', file=sys.stderr)
        raise SystemExit(1)
print('CLI validada sem aliases em inglês e sem --calibrado.')

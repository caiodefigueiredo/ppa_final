import json
import socket
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

CODIFICACAO = 'utf-8'


def agora() -> float:
    return time.perf_counter()


def enviar_json(conexao: socket.socket, mensagem: Dict[str, Any]) -> None:
    dados = json.dumps(mensagem, separators=(',', ':')).encode(CODIFICACAO) + b'\n'
    conexao.sendall(dados)


def receber_json(arquivo_conexao) -> Optional[Dict[str, Any]]:
    linha = arquivo_conexao.readline()
    if not linha:
        return None
    if isinstance(linha, bytes):
        linha = linha.decode(CODIFICACAO)
    return json.loads(linha)


@dataclass
class BlocoIntervalo:
    inicio: int
    fim: int

    @property
    def tamanho(self) -> int:
        return max(0, self.fim - self.inicio + 1)

    def para_dict(self) -> Dict[str, int]:
        return asdict(self)


def estimar_custo_intervalo(inicio: int, fim: int) -> float:
    """Estimativa simples de custo para normalização.

    Para teste por divisão até sqrt(n), intervalos com números maiores tendem a
    custar mais. A função não precisa ser perfeita; ela serve para suavizar a
    decisão adaptativa e reduzir o viés temporal de ranges crescentes.
    """
    if fim < inicio:
        return 0.0
    meio = (inicio + fim) / 2.0
    return (fim - inicio + 1) * max(meio, 1.0) ** 0.5


def criar_blocos_ordenados(inicio: int, fim: int, tamanho_bloco: int) -> List[BlocoIntervalo]:
    blocos: List[BlocoIntervalo] = []
    atual = inicio
    while atual <= fim:
        fim_bloco = min(fim, atual + tamanho_bloco - 1)
        blocos.append(BlocoIntervalo(atual, fim_bloco))
        atual = fim_bloco + 1
    return blocos


def intercalar_baixo_alto(blocos: List[BlocoIntervalo]) -> List[BlocoIntervalo]:
    resultado: List[BlocoIntervalo] = []
    baixo, alto = 0, len(blocos) - 1
    while baixo <= alto:
        resultado.append(blocos[baixo])
        if baixo != alto:
            resultado.append(blocos[alto])
        baixo += 1
        alto -= 1
    return resultado

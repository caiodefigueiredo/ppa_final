import json
import socket
import time
from typing import Any, Dict, Optional

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


def conectar_com_tentativas(endereco: str, porta: int, tentativas: int = 60, espera: float = 0.5) -> socket.socket:
    ultimo_erro = None
    for _ in range(tentativas):
        try:
            conexao = socket.create_connection((endereco, porta), timeout=5)
            conexao.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return conexao
        except OSError as erro:
            ultimo_erro = erro
            time.sleep(espera)
    raise ConnectionError(f'Não foi possível conectar a {endereco}:{porta}: {ultimo_erro}')
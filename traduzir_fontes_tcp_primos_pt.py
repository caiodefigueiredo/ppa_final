from pathlib import Path

BASE = Path('/home/ubuntu/escalonamento_tcp_primos')
SRC = BASE / 'src'

arquivos = {}

arquivos['src/common.py'] = r'''import json
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
'''

arquivos['src/prime.py'] = r'''from math import isqrt
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
'''

arquivos['src/storage.py'] = r'''import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

ESQUEMA = ''' + '"""' + r'''
CREATE TABLE IF NOT EXISTS execucoes (
    id_execucao INTEGER PRIMARY KEY AUTOINCREMENT,
    modo TEXT NOT NULL,
    valor_inicio INTEGER NOT NULL,
    valor_fim INTEGER NOT NULL,
    trabalhadores_esperados INTEGER,
    modo_unidade TEXT,
    inicio_em REAL NOT NULL,
    fim_em REAL,
    segundos_totais REAL,
    total_primos INTEGER DEFAULT 0,
    total_numeros INTEGER DEFAULT 0,
    vazao_numeros_por_segundo REAL DEFAULT 0,
    observacoes TEXT
);

CREATE TABLE IF NOT EXISTS tarefas (
    id_tarefa INTEGER PRIMARY KEY,
    id_execucao INTEGER NOT NULL,
    id_trabalhador TEXT,
    modo TEXT NOT NULL,
    intervalos_json TEXT NOT NULL,
    quantidade_numeros INTEGER NOT NULL,
    quantidade_primos INTEGER NOT NULL,
    janela_antes REAL,
    janela_depois REAL,
    custo_estimado REAL,
    segundos_trabalhador REAL NOT NULL,
    segundos_ida_volta REAL,
    criado_em REAL NOT NULL,
    fim_em REAL NOT NULL,
    FOREIGN KEY(id_execucao) REFERENCES execucoes(id_execucao)
);

CREATE TABLE IF NOT EXISTS trabalhadores (
    id_execucao INTEGER NOT NULL,
    id_trabalhador TEXT NOT NULL,
    maquina TEXT,
    nucleos INTEGER,
    registrado_em REAL,
    tarefas_concluidas INTEGER DEFAULT 0,
    numeros_processados INTEGER DEFAULT 0,
    primos_encontrados INTEGER DEFAULT 0,
    total_segundos_trabalhador REAL DEFAULT 0,
    PRIMARY KEY(id_execucao, id_trabalhador),
    FOREIGN KEY(id_execucao) REFERENCES execucoes(id_execucao)
);
''' + '"""' + r'''


class Armazenamento:
    def __init__(self, caminho_banco: str):
        self.caminho_banco = str(Path(caminho_banco))
        self.conexao = sqlite3.connect(self.caminho_banco, check_same_thread=False)
        self.conexao.execute('PRAGMA journal_mode=WAL')
        self.conexao.executescript(ESQUEMA)
        self.conexao.commit()

    def fechar(self) -> None:
        self.conexao.close()

    def criar_execucao(self, modo: str, valor_inicio: int, valor_fim: int, trabalhadores_esperados: Optional[int], modo_unidade: str, observacoes: str = '') -> int:
        cursor = self.conexao.execute(
            'INSERT INTO execucoes(modo,valor_inicio,valor_fim,trabalhadores_esperados,modo_unidade,inicio_em,observacoes,total_numeros) VALUES(?,?,?,?,?,?,?,?)',
            (modo, valor_inicio, valor_fim, trabalhadores_esperados, modo_unidade, time.time(), observacoes, max(0, valor_fim - valor_inicio + 1)),
        )
        self.conexao.commit()
        return int(cursor.lastrowid)

    def finalizar_execucao(self, id_execucao: int, segundos_totais: float, total_primos: int) -> None:
        total_numeros = self.conexao.execute('SELECT total_numeros FROM execucoes WHERE id_execucao=?', (id_execucao,)).fetchone()[0]
        vazao = total_numeros / segundos_totais if segundos_totais > 0 else 0
        self.conexao.execute(
            'UPDATE execucoes SET fim_em=?, segundos_totais=?, total_primos=?, vazao_numeros_por_segundo=? WHERE id_execucao=?',
            (time.time(), segundos_totais, total_primos, vazao, id_execucao),
        )
        self.conexao.commit()

    def adicionar_trabalhador(self, id_execucao: int, id_trabalhador: str, maquina: str, nucleos: int) -> None:
        self.conexao.execute(
            'INSERT OR REPLACE INTO trabalhadores(id_execucao,id_trabalhador,maquina,nucleos,registrado_em) VALUES(?,?,?,?,?)',
            (id_execucao, id_trabalhador, maquina, nucleos, time.time()),
        )
        self.conexao.commit()

    def adicionar_tarefa(self, id_execucao: int, tarefa: Dict[str, Any]) -> None:
        self.conexao.execute(
            """INSERT OR REPLACE INTO tarefas(id_tarefa,id_execucao,id_trabalhador,modo,intervalos_json,quantidade_numeros,quantidade_primos,
               janela_antes,janela_depois,custo_estimado,segundos_trabalhador,segundos_ida_volta,criado_em,fim_em)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                tarefa['id_tarefa'], id_execucao, tarefa.get('id_trabalhador'), tarefa['modo'], tarefa['intervalos_json'], tarefa['quantidade_numeros'],
                tarefa['quantidade_primos'], tarefa.get('janela_antes'), tarefa.get('janela_depois'), tarefa.get('custo_estimado'),
                tarefa['segundos_trabalhador'], tarefa.get('segundos_ida_volta'), tarefa['criado_em'], tarefa['fim_em'],
            ),
        )
        if tarefa.get('id_trabalhador'):
            self.conexao.execute(
                """UPDATE trabalhadores SET tarefas_concluidas=tarefas_concluidas+1, numeros_processados=numeros_processados+?, primos_encontrados=primos_encontrados+?,
                   total_segundos_trabalhador=total_segundos_trabalhador+? WHERE id_execucao=? AND id_trabalhador=?""",
                (tarefa['quantidade_numeros'], tarefa['quantidade_primos'], tarefa['segundos_trabalhador'], id_execucao, tarefa['id_trabalhador']),
            )
        self.conexao.commit()

# Alias mantido para compatibilidade com imports antigos.
Storage = Armazenamento
'''

arquivos['src/worker_node.py'] = r'''import argparse
import os
import socket
import time
from typing import List, Tuple

from common import conectar_com_tentativas, enviar_json, receber_json
from prime import contar_primos_varios_intervalos


def interpretar_nucleos(valor: str) -> int:
    if valor == 'auto':
        return max(1, os.cpu_count() or 1)
    return max(1, int(valor))


def executar_trabalhador(endereco_mestre: str, porta_mestre: int, id_trabalhador: str, nucleos: int, fator_lentidao: float = 1.0) -> None:
    conexao = conectar_com_tentativas(endereco_mestre, porta_mestre)
    arquivo_conexao = conexao.makefile('r')
    enviar_json(conexao, {
        'tipo': 'registro',
        'id_trabalhador': id_trabalhador,
        'nucleos': nucleos,
        'pid': os.getpid(),
        'maquina': socket.gethostname(),
        'fator_lentidao': fator_lentidao,
    })
    while True:
        mensagem = receber_json(arquivo_conexao)
        if mensagem is None:
            break
        if mensagem.get('tipo') == 'encerrar':
            enviar_json(conexao, {'tipo': 'tchau', 'id_trabalhador': id_trabalhador})
            break
        if mensagem.get('tipo') != 'tarefa':
            continue
        id_tarefa = mensagem['id_tarefa']
        intervalos: List[Tuple[int, int]] = [(int(r['inicio']), int(r['fim'])) for r in mensagem['intervalos']]
        inicio_tempo = time.perf_counter()
        primos = contar_primos_varios_intervalos(intervalos, nucleos=nucleos)
        if fator_lentidao > 1.0:
            # Recurso opcional para simular heterogeneidade em testes locais.
            time.sleep((fator_lentidao - 1.0) * 0.01)
        tempo_decorrido = time.perf_counter() - inicio_tempo
        quantidade_numeros = sum(max(0, fim - inicio + 1) for inicio, fim in intervalos)
        enviar_json(conexao, {
            'tipo': 'resultado',
            'id_tarefa': id_tarefa,
            'id_trabalhador': id_trabalhador,
            'quantidade_primos': primos,
            'quantidade_numeros': quantidade_numeros,
            'segundos_trabalhador': tempo_decorrido,
        })
    try:
        conexao.close()
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description='Trabalhador para contagem de primos via socket.')
    parser.add_argument('--endereco-mestre', '--master-host', dest='endereco_mestre', required=True)
    parser.add_argument('--porta-mestre', '--master-port', dest='porta_mestre', type=int, default=9000)
    parser.add_argument('--id-trabalhador', '--worker-id', dest='id_trabalhador', default=None)
    parser.add_argument('--nucleos', '--cores', dest='nucleos', default='auto', help='auto ou número inteiro')
    parser.add_argument('--fator-lentidao', '--speed-factor', dest='fator_lentidao', type=float, default=1.0, help='Opcional para simular trabalhador mais lento em testes locais')
    argumentos = parser.parse_args()
    id_trabalhador = argumentos.id_trabalhador or f'{socket.gethostname()}-{os.getpid()}'
    executar_trabalhador(argumentos.endereco_mestre, argumentos.porta_mestre, id_trabalhador, interpretar_nucleos(argumentos.nucleos), argumentos.fator_lentidao)


if __name__ == '__main__':
    main()
'''

arquivos['src/master.py'] = r'''import argparse
import json
import random
import socket
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from common import BlocoIntervalo, criar_blocos_ordenados, enviar_json, estimar_custo_intervalo, intercalar_baixo_alto, receber_json
from storage import Armazenamento


@dataclass
class ConexaoTrabalhador:
    id_trabalhador: str
    conexao: socket.socket
    arquivo_conexao: object
    maquina: str
    nucleos: int
    fator_lentidao: float = 1.0
    ocupado: bool = False
    id_tarefa_atual: Optional[int] = None
    enviado_em: float = 0.0
    janela: float = 1.0
    tarefas_concluidas: int = 0
    numeros_processados: int = 0
    primos_encontrados: int = 0


@dataclass
class MetadadosTarefa:
    id_tarefa: int
    id_trabalhador: str
    intervalos: List[BlocoIntervalo]
    modo: str
    janela_antes: float
    custo_estimado: float
    criado_em: float


class Mestre:
    def __init__(self, argumentos: argparse.Namespace):
        self.argumentos = argumentos
        self.armazenamento = Armazenamento(argumentos.banco)
        self.id_execucao = self.armazenamento.criar_execucao(argumentos.modo, argumentos.inicio, argumentos.fim, argumentos.trabalhadores_esperados, argumentos.modo_unidade, observacoes='execução mestre-trabalhador por socket')
        self.trabalhadores: Dict[str, ConexaoTrabalhador] = {}
        self.blocos_pendentes: List[BlocoIntervalo] = []
        self.proximo_inicio_intervalo = argumentos.inicio
        self.contador_tarefa = 0
        self.tarefas: Dict[int, MetadadosTarefa] = {}
        self.total_primos = 0
        self.total_numeros_processados = 0
        self.trava = threading.Lock()
        self.evento_concluido = threading.Event()

    def preparar_blocos(self) -> None:
        if self.argumentos.modo_unidade == 'blocos':
            blocos = criar_blocos_ordenados(self.argumentos.inicio, self.argumentos.fim, self.argumentos.tamanho_bloco_base)
            if self.argumentos.ordem_blocos == 'embaralhado':
                aleatorio = random.Random(self.argumentos.semente)
                aleatorio.shuffle(blocos)
            elif self.argumentos.ordem_blocos == 'intercalado':
                blocos = intercalar_baixo_alto(blocos)
            self.blocos_pendentes = blocos

    def iniciar_servidor(self) -> socket.socket:
        servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        servidor.bind((self.argumentos.endereco, self.argumentos.porta))
        servidor.listen()
        return servidor

    def aceitar_trabalhadores(self, servidor: socket.socket) -> None:
        print(f'[mestre] aguardando {self.argumentos.trabalhadores_esperados} trabalhadores em {self.argumentos.endereco}:{self.argumentos.porta}...')
        while len(self.trabalhadores) < self.argumentos.trabalhadores_esperados:
            conexao, endereco_cliente = servidor.accept()
            conexao.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            arquivo_conexao = conexao.makefile('r')
            mensagem = receber_json(arquivo_conexao)
            if not mensagem or mensagem.get('tipo') != 'registro':
                conexao.close()
                continue
            id_trabalhador = mensagem['id_trabalhador']
            trabalhador = ConexaoTrabalhador(
                id_trabalhador=id_trabalhador,
                conexao=conexao,
                arquivo_conexao=arquivo_conexao,
                maquina=mensagem.get('maquina', endereco_cliente[0]),
                nucleos=int(mensagem.get('nucleos', 1)),
                fator_lentidao=float(mensagem.get('fator_lentidao', 1.0)),
                janela=float(self.argumentos.janela_inicial),
            )
            self.trabalhadores[id_trabalhador] = trabalhador
            self.armazenamento.adicionar_trabalhador(self.id_execucao, id_trabalhador, trabalhador.maquina, trabalhador.nucleos)
            print(f'[mestre] trabalhador registrado: {id_trabalhador}, máquina={trabalhador.maquina}, núcleos={trabalhador.nucleos}')
            thread = threading.Thread(target=self.escutar_trabalhador, args=(trabalhador,), daemon=True)
            thread.start()

    def existe_trabalho_pendente(self) -> bool:
        if self.argumentos.modo_unidade == 'blocos':
            return bool(self.blocos_pendentes)
        return self.proximo_inicio_intervalo <= self.argumentos.fim

    def alocar_intervalos(self, trabalhador: ConexaoTrabalhador) -> List[BlocoIntervalo]:
        if self.argumentos.modo_unidade == 'blocos':
            quantidade_blocos = max(1, int(round(trabalhador.janela)))
            alocados = self.blocos_pendentes[:quantidade_blocos]
            self.blocos_pendentes = self.blocos_pendentes[quantidade_blocos:]
            return alocados
        tamanho = max(1, int(round(trabalhador.janela)))
        inicio = self.proximo_inicio_intervalo
        fim = min(self.argumentos.fim, inicio + tamanho - 1)
        self.proximo_inicio_intervalo = fim + 1
        return [BlocoIntervalo(inicio, fim)]

    def despachar_se_possivel(self, trabalhador: ConexaoTrabalhador) -> None:
        with self.trava:
            if trabalhador.ocupado or not self.existe_trabalho_pendente():
                return
            intervalos = self.alocar_intervalos(trabalhador)
            if not intervalos:
                return
            self.contador_tarefa += 1
            id_tarefa = self.contador_tarefa
            custo_estimado = sum(estimar_custo_intervalo(intervalo.inicio, intervalo.fim) for intervalo in intervalos)
            metadados = MetadadosTarefa(id_tarefa, trabalhador.id_trabalhador, intervalos, self.argumentos.modo, trabalhador.janela, custo_estimado, time.perf_counter())
            self.tarefas[id_tarefa] = metadados
            trabalhador.ocupado = True
            trabalhador.id_tarefa_atual = id_tarefa
            trabalhador.enviado_em = metadados.criado_em
            mensagem = {'tipo': 'tarefa', 'id_tarefa': id_tarefa, 'modo': self.argumentos.modo, 'intervalos': [intervalo.para_dict() for intervalo in intervalos]}
        enviar_json(trabalhador.conexao, mensagem)

    def ajustar_janela(self, trabalhador: ConexaoTrabalhador, segundos_trabalhador: float, metadados: MetadadosTarefa) -> None:
        if self.argumentos.modo == 'estatico':
            return
        tempo_decisao = segundos_trabalhador
        if self.argumentos.calibrado and metadados.custo_estimado > 0:
            unidades_por_segundo = metadados.custo_estimado / max(segundos_trabalhador, 1e-9)
            referencia = getattr(trabalhador, 'referencia_unidades_por_segundo', None)
            if referencia is None:
                setattr(trabalhador, 'referencia_unidades_por_segundo', unidades_por_segundo)
                tempo_decisao = self.argumentos.tempo_alvo
            else:
                tempo_decisao = self.argumentos.tempo_alvo * (referencia / max(unidades_por_segundo, 1e-9))
        if tempo_decisao <= self.argumentos.tempo_alvo:
            trabalhador.janela = min(self.argumentos.janela_maxima, trabalhador.janela + self.argumentos.passo_aditivo)
        else:
            trabalhador.janela = max(self.argumentos.janela_minima, trabalhador.janela * self.argumentos.fator_reducao)

    def escutar_trabalhador(self, trabalhador: ConexaoTrabalhador) -> None:
        while not self.evento_concluido.is_set():
            mensagem = receber_json(trabalhador.arquivo_conexao)
            if mensagem is None:
                break
            if mensagem.get('tipo') == 'resultado':
                self.tratar_resultado(trabalhador, mensagem)
                self.despachar_se_possivel(trabalhador)
                self.verificar_conclusao()

    def tratar_resultado(self, trabalhador: ConexaoTrabalhador, mensagem: dict) -> None:
        fim_em = time.perf_counter()
        with self.trava:
            id_tarefa = int(mensagem['id_tarefa'])
            metadados = self.tarefas.pop(id_tarefa)
            segundos_trabalhador = float(mensagem['segundos_trabalhador'])
            segundos_ida_volta = fim_em - metadados.criado_em
            primos = int(mensagem['quantidade_primos'])
            numeros = int(mensagem['quantidade_numeros'])
            self.total_primos += primos
            self.total_numeros_processados += numeros
            trabalhador.ocupado = False
            trabalhador.id_tarefa_atual = None
            trabalhador.tarefas_concluidas += 1
            trabalhador.numeros_processados += numeros
            trabalhador.primos_encontrados += primos
            self.ajustar_janela(trabalhador, segundos_trabalhador, metadados)
            self.armazenamento.adicionar_tarefa(self.id_execucao, {
                'id_tarefa': id_tarefa,
                'id_trabalhador': trabalhador.id_trabalhador,
                'modo': self.argumentos.modo,
                'intervalos_json': json.dumps([intervalo.para_dict() for intervalo in metadados.intervalos]),
                'quantidade_numeros': numeros,
                'quantidade_primos': primos,
                'janela_antes': metadados.janela_antes,
                'janela_depois': trabalhador.janela,
                'custo_estimado': metadados.custo_estimado,
                'segundos_trabalhador': segundos_trabalhador,
                'segundos_ida_volta': segundos_ida_volta,
                'criado_em': metadados.criado_em,
                'fim_em': fim_em,
            })
            print(f"[mestre] tarefa={id_tarefa} trabalhador={trabalhador.id_trabalhador} números={numeros} primos={primos} tempo={segundos_trabalhador:.4f}s janela {metadados.janela_antes:.1f}->{trabalhador.janela:.1f}")

    def verificar_conclusao(self) -> None:
        with self.trava:
            algum_ocupado = any(t.ocupado for t in self.trabalhadores.values())
            if not self.existe_trabalho_pendente() and not algum_ocupado and not self.tarefas:
                self.evento_concluido.set()

    def executar(self) -> None:
        self.preparar_blocos()
        servidor = self.iniciar_servidor()
        self.aceitar_trabalhadores(servidor)
        inicio_tempo = time.perf_counter()
        for trabalhador in list(self.trabalhadores.values()):
            self.despachar_se_possivel(trabalhador)
        self.evento_concluido.wait()
        segundos_totais = time.perf_counter() - inicio_tempo
        self.armazenamento.finalizar_execucao(self.id_execucao, segundos_totais, self.total_primos)
        for trabalhador in self.trabalhadores.values():
            try:
                enviar_json(trabalhador.conexao, {'tipo': 'encerrar'})
                trabalhador.conexao.close()
            except OSError:
                pass
        servidor.close()
        print(f'[mestre] execução finalizada. id_execucao={self.id_execucao} total_primos={self.total_primos} tempo={segundos_totais:.4f}s números={self.total_numeros_processados}')
        self.armazenamento.fechar()


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Mestre para escalonamento paralelo de intervalos de primos.')
    parser.add_argument('--endereco', '--host', dest='endereco', default='0.0.0.0')
    parser.add_argument('--porta', '--port', dest='porta', type=int, default=9000)
    parser.add_argument('--trabalhadores-esperados', '--expected-workers', dest='trabalhadores_esperados', type=int, required=True)
    parser.add_argument('--inicio', '--start', dest='inicio', type=int, required=True)
    parser.add_argument('--fim', '--end', dest='fim', type=int, required=True)
    parser.add_argument('--modo', '--mode', dest='modo', choices=['estatico', 'adaptativo', 'static', 'adaptive'], default='adaptativo')
    parser.add_argument('--modo-unidade', '--unit-mode', dest='modo_unidade', choices=['intervalo', 'blocos', 'range', 'blocks'], default='blocos')
    parser.add_argument('--tamanho-bloco-base', '--base-block-size', dest='tamanho_bloco_base', type=int, default=10000)
    parser.add_argument('--ordem-blocos', '--block-order', dest='ordem_blocos', choices=['ordenado', 'embaralhado', 'intercalado', 'ordered', 'shuffle', 'interleave'], default='intercalado')
    parser.add_argument('--semente', '--seed', dest='semente', type=int, default=42)
    parser.add_argument('--janela-inicial', '--initial-window', dest='janela_inicial', type=float, default=2.0, help='tamanho do intervalo em modo_unidade=intervalo ou quantidade de blocos em modo_unidade=blocos')
    parser.add_argument('--janela-minima', '--min-window', dest='janela_minima', type=float, default=1.0)
    parser.add_argument('--janela-maxima', '--max-window', dest='janela_maxima', type=float, default=64.0)
    parser.add_argument('--passo-aditivo', '--additive-step', dest='passo_aditivo', type=float, default=1.0)
    parser.add_argument('--fator-reducao', '--decrease-factor', dest='fator_reducao', type=float, default=0.5)
    parser.add_argument('--tempo-alvo', '--target-time', dest='tempo_alvo', type=float, default=0.5)
    parser.add_argument('--calibrado', '--calibrated', dest='calibrado', action='store_true')
    parser.add_argument('--banco', '--db', dest='banco', default='resultados.db')
    return parser


def normalizar_argumentos(argumentos: argparse.Namespace) -> argparse.Namespace:
    if argumentos.modo == 'static':
        argumentos.modo = 'estatico'
    elif argumentos.modo == 'adaptive':
        argumentos.modo = 'adaptativo'
    if argumentos.modo_unidade == 'range':
        argumentos.modo_unidade = 'intervalo'
    elif argumentos.modo_unidade == 'blocks':
        argumentos.modo_unidade = 'blocos'
    mapa_ordem = {'ordered': 'ordenado', 'shuffle': 'embaralhado', 'interleave': 'intercalado'}
    argumentos.ordem_blocos = mapa_ordem.get(argumentos.ordem_blocos, argumentos.ordem_blocos)
    return argumentos


def main() -> None:
    argumentos = normalizar_argumentos(criar_parser().parse_args())
    if argumentos.fim < argumentos.inicio:
        raise SystemExit('--fim deve ser maior ou igual a --inicio')
    Mestre(argumentos).executar()


if __name__ == '__main__':
    main()
'''

arquivos['src/run_sequential.py'] = r'''import argparse
import json
import time

from prime import contar_primos_intervalo
from storage import Armazenamento


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
'''

arquivos['src/run_local_experiment.py'] = r'''import argparse
import subprocess
import sys
import time
from pathlib import Path


def normalizar_modo(modo: str) -> str:
    return {'static': 'estatico', 'adaptive': 'adaptativo'}.get(modo, modo)


def normalizar_unidade(unidade: str) -> str:
    return {'range': 'intervalo', 'blocks': 'blocos'}.get(unidade, unidade)


def main() -> None:
    parser = argparse.ArgumentParser(description='Executa mestre e trabalhadores locais para validação rápida.')
    parser.add_argument('--inicio', '--start', dest='inicio', type=int, required=True)
    parser.add_argument('--fim', '--end', dest='fim', type=int, required=True)
    parser.add_argument('--trabalhadores', '--workers', dest='trabalhadores', type=int, default=3)
    parser.add_argument('--modo', '--mode', dest='modo', choices=['estatico', 'adaptativo', 'static', 'adaptive'], default='adaptativo')
    parser.add_argument('--modo-unidade', '--unit-mode', dest='modo_unidade', choices=['intervalo', 'blocos', 'range', 'blocks'], default='blocos')
    parser.add_argument('--nucleos-trabalhador', '--worker-cores', dest='nucleos_trabalhador', default='1')
    parser.add_argument('--porta', '--port', dest='porta', type=int, default=9000)
    parser.add_argument('--banco', '--db', dest='banco', default='resultados.db')
    parser.add_argument('--tamanho-bloco-base', '--base-block-size', dest='tamanho_bloco_base', type=int, default=10000)
    parser.add_argument('--tempo-alvo', '--target-time', dest='tempo_alvo', type=float, default=0.5)
    parser.add_argument('--calibrado', '--calibrated', dest='calibrado', action='store_true')
    argumentos = parser.parse_args()

    diretorio_src = Path(__file__).resolve().parent
    modo = normalizar_modo(argumentos.modo)
    modo_unidade = normalizar_unidade(argumentos.modo_unidade)
    comando_mestre = [
        sys.executable, str(diretorio_src / 'master.py'),
        '--endereco', '127.0.0.1', '--porta', str(argumentos.porta), '--trabalhadores-esperados', str(argumentos.trabalhadores),
        '--inicio', str(argumentos.inicio), '--fim', str(argumentos.fim), '--modo', modo,
        '--modo-unidade', modo_unidade, '--tamanho-bloco-base', str(argumentos.tamanho_bloco_base),
        '--tempo-alvo', str(argumentos.tempo_alvo), '--banco', argumentos.banco,
    ]
    if argumentos.calibrado:
        comando_mestre.append('--calibrado')

    mestre = subprocess.Popen(comando_mestre)
    trabalhadores = []
    try:
        time.sleep(0.8)
        for indice in range(argumentos.trabalhadores):
            fator_lentidao = 1.0 + (indice % 3) * 0.6
            comando_trabalhador = [
                sys.executable, str(diretorio_src / 'worker_node.py'), '--endereco-mestre', '127.0.0.1', '--porta-mestre', str(argumentos.porta),
                '--id-trabalhador', f'trabalhador-local-{indice+1}', '--nucleos', argumentos.nucleos_trabalhador, '--fator-lentidao', str(fator_lentidao),
            ]
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
'''

arquivos['src/plot_results.py'] = r'''import argparse
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description='Gera gráficos simples a partir do SQLite.')
    parser.add_argument('--banco', '--db', dest='banco', default='resultados.db')
    parser.add_argument('--saida', '--out-dir', dest='saida', default='graficos')
    argumentos = parser.parse_args()

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        raise SystemExit('Instale matplotlib para gerar gráficos: pip install matplotlib')

    saida = Path(argumentos.saida)
    saida.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(argumentos.banco)

    execucoes = conexao.execute('SELECT id_execucao, modo, segundos_totais, vazao_numeros_por_segundo FROM execucoes ORDER BY id_execucao').fetchall()
    if execucoes:
        rotulos = [f'{linha[0]}-{linha[1]}' for linha in execucoes]
        tempos = [linha[2] or 0 for linha in execucoes]
        plt.figure(figsize=(10, 5))
        plt.bar(rotulos, tempos)
        plt.ylabel('Tempo total (s)')
        plt.xlabel('Execução')
        plt.title('Comparação de tempo total por execução')
        plt.xticks(rotation=30, ha='right')
        plt.tight_layout()
        plt.savefig(saida / 'tempo_total.png', dpi=150)
        plt.close()

        vazoes = [linha[3] or 0 for linha in execucoes]
        plt.figure(figsize=(10, 5))
        plt.bar(rotulos, vazoes)
        plt.ylabel('Números processados por segundo')
        plt.xlabel('Execução')
        plt.title('Throughput por execução')
        plt.xticks(rotation=30, ha='right')
        plt.tight_layout()
        plt.savefig(saida / 'throughput.png', dpi=150)
        plt.close()

    tarefas = conexao.execute('SELECT id_tarefa, id_trabalhador, janela_antes, janela_depois FROM tarefas WHERE janela_antes IS NOT NULL ORDER BY id_tarefa').fetchall()
    if tarefas:
        por_trabalhador = {}
        for id_tarefa, id_trabalhador, antes, depois in tarefas:
            por_trabalhador.setdefault(id_trabalhador, []).append((id_tarefa, depois))
        plt.figure(figsize=(10, 5))
        for id_trabalhador, valores in por_trabalhador.items():
            plt.plot([valor[0] for valor in valores], [valor[1] for valor in valores], marker='o', label=id_trabalhador)
        plt.ylabel('Janela após ajuste')
        plt.xlabel('Tarefa')
        plt.title('Evolução da janela adaptativa por trabalhador')
        plt.legend()
        plt.tight_layout()
        plt.savefig(saida / 'evolucao_janela.png', dpi=150)
        plt.close()

    linhas_trabalhadores = conexao.execute('SELECT id_execucao, id_trabalhador, numeros_processados, total_segundos_trabalhador FROM trabalhadores ORDER BY id_execucao, id_trabalhador').fetchall()
    if linhas_trabalhadores:
        rotulos = [f'{linha[0]}-{linha[1]}' for linha in linhas_trabalhadores]
        numeros = [linha[2] for linha in linhas_trabalhadores]
        plt.figure(figsize=(10, 5))
        plt.bar(rotulos, numeros)
        plt.ylabel('Números processados')
        plt.xlabel('Trabalhador')
        plt.title('Distribuição de carga por trabalhador')
        plt.xticks(rotation=30, ha='right')
        plt.tight_layout()
        plt.savefig(saida / 'carga_por_trabalhador.png', dpi=150)
        plt.close()

    conexao.close()
    print(f'Gráficos salvos em: {saida.resolve()}')


if __name__ == '__main__':
    main()
'''

arquivos['README.md'] = r'''# Escalonamento paralelo adaptativo inspirado no TCP

Este projeto implementa, em Python, um protótipo de **escalonamento paralelo adaptativo** inspirado em conceitos da camada TCP. O sistema possui um processo **mestre**, vários **trabalhadores** e três modos de avaliação: execução sequencial, paralela estática e paralela adaptativa.

A versão atual usa nomes em português nas variáveis principais, nos campos das mensagens entre mestre e trabalhadores e nas tabelas SQLite. Alguns argumentos antigos em inglês foram mantidos como aliases para facilitar compatibilidade, mas a documentação recomenda os nomes em português.

## Estrutura

| Arquivo | Função |
|---|---|
| `src/master.py` | Processo mestre responsável por distribuir intervalos e ajustar janelas. |
| `src/worker_node.py` | Processo trabalhador responsável por contar primos nos intervalos recebidos. |
| `src/run_sequential.py` | Linha de base sequencial. |
| `src/run_local_experiment.py` | Executa mestre e trabalhadores locais automaticamente. |
| `src/storage.py` | Persistência SQLite com tabelas `execucoes`, `tarefas` e `trabalhadores`. |
| `src/plot_results.py` | Gera gráficos a partir do banco de resultados. |

## Execução rápida

```bash
python3 src/run_sequential.py --inicio 1000000 --fim 1200000 --banco resultados.db

python3 src/run_local_experiment.py \
  --inicio 1000000 \
  --fim 1400000 \
  --trabalhadores 3 \
  --modo adaptativo \
  --nucleos-trabalhador 1 \
  --porta 9101 \
  --banco resultados.db \
  --tamanho-bloco-base 10000 \
  --tempo-alvo 0.4

python3 src/run_local_experiment.py \
  --inicio 1000000 \
  --fim 1400000 \
  --trabalhadores 3 \
  --modo estatico \
  --nucleos-trabalhador 1 \
  --porta 9102 \
  --banco resultados.db \
  --tamanho-bloco-base 10000

python3 src/plot_results.py --banco resultados.db --saida graficos
```

## Campos principais do SQLite

| Tabela | Campos principais |
|---|---|
| `execucoes` | `id_execucao`, `modo`, `valor_inicio`, `valor_fim`, `segundos_totais`, `total_primos`, `vazao_numeros_por_segundo`. |
| `tarefas` | `id_tarefa`, `id_trabalhador`, `intervalos_json`, `quantidade_numeros`, `quantidade_primos`, `janela_antes`, `janela_depois`. |
| `trabalhadores` | `id_trabalhador`, `maquina`, `nucleos`, `tarefas_concluidas`, `numeros_processados`, `primos_encontrados`. |
'''

arquivos['COMO_EXECUTAR.md'] = r'''# Como executar e avaliar o projeto

Este documento explica como utilizar os fontes Python do projeto **Escalonamento paralelo adaptativo inspirado no TCP para ambiente heterogêneo**. A implementação usa nomes em português para variáveis principais, mensagens e campos do banco SQLite.

## Modos de execução

| Modo | Arquivo principal | Papel na avaliação |
|---|---|---|
| Sequencial | `src/run_sequential.py` | Mede o tempo base para comparação. |
| Paralelo estático | `src/master.py --modo estatico` | Mede o ganho paralelo sem adaptação dinâmica. |
| Paralelo adaptativo | `src/master.py --modo adaptativo` | Mede o efeito da adaptação individual por trabalhador. |
| Teste local integrado | `src/run_local_experiment.py` | Inicia mestre e trabalhadores locais automaticamente. |
| Gráficos | `src/plot_results.py` | Gera visualizações a partir do SQLite. |

## Execução rápida em uma máquina

```bash
cd escalonamento_tcp_primos
python3 src/run_sequential.py --inicio 1000000 --fim 1200000 --banco resultados.db
```

Modo adaptativo com três trabalhadores locais:

```bash
python3 src/run_local_experiment.py \
  --inicio 1000000 \
  --fim 1400000 \
  --trabalhadores 3 \
  --modo adaptativo \
  --nucleos-trabalhador 1 \
  --porta 9101 \
  --banco resultados.db \
  --tamanho-bloco-base 10000 \
  --tempo-alvo 0.4
```

Modo estático:

```bash
python3 src/run_local_experiment.py \
  --inicio 1000000 \
  --fim 1400000 \
  --trabalhadores 3 \
  --modo estatico \
  --nucleos-trabalhador 1 \
  --porta 9102 \
  --banco resultados.db \
  --tamanho-bloco-base 10000
```

Geração de gráficos:

```bash
python3 src/plot_results.py --banco resultados.db --saida graficos
```

## Execução distribuída com sockets

Em cada trabalhador:

```bash
python3 src/worker_node.py \
  --endereco-mestre IP_DO_MESTRE \
  --porta-mestre 9000 \
  --id-trabalhador trabalhador-01 \
  --nucleos auto
```

No mestre:

```bash
python3 src/master.py \
  --endereco 0.0.0.0 \
  --porta 9000 \
  --trabalhadores-esperados 3 \
  --inicio 1000000 \
  --fim 5000000 \
  --modo adaptativo \
  --modo-unidade blocos \
  --tamanho-bloco-base 10000 \
  --tempo-alvo 0.5 \
  --banco resultados.db
```

## Campos das tabelas

| Tabela | Descrição |
|---|---|
| `execucoes` | Guarda cada rodada experimental, com `id_execucao`, `modo`, `valor_inicio`, `valor_fim`, `segundos_totais`, `total_primos` e `vazao_numeros_por_segundo`. |
| `tarefas` | Guarda cada pacote enviado, com `id_tarefa`, `id_trabalhador`, `intervalos_json`, `quantidade_numeros`, `quantidade_primos`, `janela_antes`, `janela_depois` e tempos. |
| `trabalhadores` | Guarda estatísticas agregadas por trabalhador, como `numeros_processados`, `primos_encontrados` e `total_segundos_trabalhador`. |

## Relação com PCAM

| Etapa PCAM | Aplicação no código |
|---|---|
| Partitioning | O range total é dividido em blocos ou intervalos menores. |
| Communication | O mestre envia tarefas por socket e recebe respostas com tempo, quantidade processada e primos encontrados. |
| Agglomeration | A janela controla o agrupamento de blocos em pacotes maiores ou menores. |
| Mapping | O mestre decide dinamicamente qual carga enviar para cada trabalhador com base em sua resposta anterior. |
'''

for caminho_relativo, conteudo in arquivos.items():
    caminho = BASE / caminho_relativo
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(conteudo, encoding='utf-8')

print(f'Fontes traduzidos para português em {BASE}')

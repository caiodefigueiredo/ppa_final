import argparse
import json
import random
import socket
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from funcoes_mestre import BlocoIntervalo, criar_blocos_ordenados, enviar_json, estimar_custo_intervalo, intercalar_baixo_alto, receber_json
from armazenamento import Armazenamento


@dataclass
class ConexaoTrabalhador:
    id_trabalhador: str
    conexao: socket.socket
    arquivo_conexao: object
    maquina: str
    nucleos: int
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

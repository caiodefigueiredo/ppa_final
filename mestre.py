import argparse
import json
import random
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from armazenamento import Armazenamento
from funcoes_mestre import BlocoIntervalo, criar_blocos_ordenados, enviar_json, estimar_custo_intervalo, intercalar_baixo_alto, receber_json


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
    ultimo_heartbeat: float = field(default_factory=time.perf_counter)
    desconectado: bool = False
    trava_envio: threading.Lock = field(default_factory=threading.Lock)


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
        self.id_execucao = self.armazenamento.criar_execucao(argumentos.modo, argumentos.inicio, argumentos.fim, argumentos.max_trabalhadores, 'blocos', observacoes='execução mestre-trabalhador por socket')
        self.trabalhadores: Dict[str, ConexaoTrabalhador] = {}
        self.blocos_pendentes: List[BlocoIntervalo] = []
        self.contador_tarefa = 0
        self.tarefas: Dict[int, MetadadosTarefa] = {}
        self.total_primos = 0
        self.total_numeros_processados = 0
        self.trava = threading.Lock()
        self.evento_concluido = threading.Event()
        self.evento_primeiro_trabalhador = threading.Event()
        self.processamento_iniciado = False

    def preparar_blocos(self) -> None:
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
        servidor.listen(self.argumentos.max_trabalhadores)
        return servidor

    def enviar_para_trabalhador(self, trabalhador: ConexaoTrabalhador, mensagem: dict) -> None:
        with trabalhador.trava_envio:
            enviar_json(trabalhador.conexao, mensagem)

    def registrar_trabalhador(self, conexao: socket.socket, arquivo_conexao: object, endereco_cliente: tuple, mensagem: dict) -> Optional[ConexaoTrabalhador]:
        id_trabalhador = mensagem['id_trabalhador']
        trabalhador = ConexaoTrabalhador(
            id_trabalhador=id_trabalhador,
            conexao=conexao,
            arquivo_conexao=arquivo_conexao,
            maquina=mensagem.get('maquina', endereco_cliente[0]),
            nucleos=int(mensagem.get('nucleos', 1)),
            janela=float(self.argumentos.janela_inicial),
            ultimo_heartbeat=time.perf_counter(),
        )
        with self.trava:
            if id_trabalhador in self.trabalhadores:
                enviar_json(conexao, {'tipo': 'encerrar', 'motivo': 'id_trabalhador duplicado'})
                conexao.close()
                return None
            if len(self.trabalhadores) >= self.argumentos.max_trabalhadores:
                enviar_json(conexao, {'tipo': 'encerrar', 'motivo': 'limite máximo de trabalhadores atingido'})
                conexao.close()
                return None
            self.trabalhadores[id_trabalhador] = trabalhador
            self.armazenamento.adicionar_trabalhador(self.id_execucao, id_trabalhador, trabalhador.maquina, trabalhador.nucleos)
            self.evento_primeiro_trabalhador.set()
        print(f'[mestre] trabalhador registrado: {id_trabalhador}, máquina={trabalhador.maquina}, núcleos={trabalhador.nucleos}')
        thread = threading.Thread(target=self.escutar_trabalhador, args=(trabalhador,), daemon=True)
        thread.start()
        return trabalhador

    def aceitar_trabalhadores(self, servidor: socket.socket) -> None:
        print(f'[mestre] aceitando dinamicamente até {self.argumentos.max_trabalhadores} trabalhadores em {self.argumentos.endereco}:{self.argumentos.porta}...')
        servidor.settimeout(1.0)
        while not self.evento_concluido.is_set():
            with self.trava:
                limite_atingido = len(self.trabalhadores) >= self.argumentos.max_trabalhadores
                processamento_iniciado = self.processamento_iniciado
                ainda_ha_trabalho = self.existe_trabalho_pendente()
            if limite_atingido:
                break
            if processamento_iniciado and not ainda_ha_trabalho:
                break
            try:
                conexao, endereco_cliente = servidor.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conexao.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            arquivo_registro = conexao.makefile('r')
            mensagem = receber_json(arquivo_registro)
            if not mensagem or mensagem.get('tipo') != 'registro':
                conexao.close()
                continue
            trabalhador = self.registrar_trabalhador(conexao, arquivo_registro, endereco_cliente, mensagem)
            if trabalhador is not None and self.processamento_iniciado:
                self.despachar_se_possivel(trabalhador)
        print('[mestre] aceitação dinâmica de trabalhadores encerrada.')

    def aguardar_trabalhadores_iniciais(self) -> None:
        print(f'[mestre] aguardando pelo menos {self.argumentos.min_trabalhadores} trabalhador(es) antes de iniciar o processamento.')
        while True:
            with self.trava:
                quantidade = len(self.trabalhadores)
            if quantidade >= self.argumentos.min_trabalhadores:
                break
            time.sleep(0.1)
        inicio_espera = time.perf_counter()
        while True:
            with self.trava:
                quantidade = len(self.trabalhadores)
            if quantidade >= self.argumentos.max_trabalhadores:
                break
            if time.perf_counter() - inicio_espera >= self.argumentos.tempo_espera_trabalhadores:
                break
            time.sleep(0.1)
        print(f'[mestre] iniciando processamento com {quantidade} trabalhador(es) conectado(s); novos trabalhadores ainda poderão entrar enquanto houver trabalho pendente.')

    def existe_trabalho_pendente(self) -> bool:
        return bool(self.blocos_pendentes)

    def devolver_tarefa_pendente(self, metadados: MetadadosTarefa) -> None:
        self.blocos_pendentes = list(metadados.intervalos) + self.blocos_pendentes

    def alocar_intervalos(self, trabalhador: ConexaoTrabalhador) -> List[BlocoIntervalo]:
        quantidade_blocos = max(1, int(round(trabalhador.janela)))
        alocados = self.blocos_pendentes[:quantidade_blocos]
        self.blocos_pendentes = self.blocos_pendentes[quantidade_blocos:]
        return alocados

    def despachar_se_possivel(self, trabalhador: ConexaoTrabalhador) -> None:
        with self.trava:
            if trabalhador.desconectado or trabalhador.id_trabalhador not in self.trabalhadores:
                return
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
        try:
            self.enviar_para_trabalhador(trabalhador, mensagem)
        except OSError:
            self.remover_trabalhador(trabalhador, 'falha ao enviar tarefa')

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
        while not self.evento_concluido.is_set() and not trabalhador.desconectado:
            try:
                mensagem = receber_json(trabalhador.arquivo_conexao)
            except (OSError, json.JSONDecodeError):
                mensagem = None
            if mensagem is None:
                break
            tipo = mensagem.get('tipo')
            if tipo == 'heartbeat':
                with self.trava:
                    if trabalhador.id_trabalhador in self.trabalhadores and not trabalhador.desconectado:
                        trabalhador.ultimo_heartbeat = time.perf_counter()
                continue
            if tipo == 'resultado':
                if self.tratar_resultado(trabalhador, mensagem):
                    self.despachar_se_possivel(trabalhador)
                    self.verificar_conclusao()
        if not self.evento_concluido.is_set() and not trabalhador.desconectado:
            self.remover_trabalhador(trabalhador, 'conexão encerrada')

    def tratar_resultado(self, trabalhador: ConexaoTrabalhador, mensagem: dict) -> bool:
        fim_em = time.perf_counter()
        with self.trava:
            if trabalhador.desconectado or trabalhador.id_trabalhador not in self.trabalhadores:
                return False
            id_tarefa = int(mensagem['id_tarefa'])
            metadados = self.tarefas.pop(id_tarefa, None)
            if metadados is None or metadados.id_trabalhador != trabalhador.id_trabalhador:
                return False
            segundos_trabalhador = float(mensagem['segundos_trabalhador'])
            segundos_ida_volta = fim_em - metadados.criado_em
            primos = int(mensagem['quantidade_primos'])
            numeros = int(mensagem['quantidade_numeros'])
            self.total_primos += primos
            self.total_numeros_processados += numeros
            trabalhador.ocupado = False
            trabalhador.id_tarefa_atual = None
            trabalhador.ultimo_heartbeat = fim_em
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
            return True

    def remover_trabalhador(self, trabalhador: ConexaoTrabalhador, motivo: str) -> None:
        metadados_reenfileirados: Optional[MetadadosTarefa] = None
        with self.trava:
            trabalhador_atual = self.trabalhadores.get(trabalhador.id_trabalhador)
            if trabalhador_atual is not trabalhador or trabalhador.desconectado:
                return
            trabalhador.desconectado = True
            self.trabalhadores.pop(trabalhador.id_trabalhador, None)
            if trabalhador.id_tarefa_atual is not None:
                metadados_reenfileirados = self.tarefas.pop(trabalhador.id_tarefa_atual, None)
                if metadados_reenfileirados is not None:
                    self.devolver_tarefa_pendente(metadados_reenfileirados)
            trabalhador.ocupado = False
            trabalhador.id_tarefa_atual = None
        if metadados_reenfileirados is not None:
            print(f'[mestre] trabalhador {trabalhador.id_trabalhador} desconectado por {motivo}; tarefa {metadados_reenfileirados.id_tarefa} devolvida para pendência.')
        else:
            print(f'[mestre] trabalhador {trabalhador.id_trabalhador} desconectado por {motivo}.')
        try:
            trabalhador.conexao.close()
        except OSError:
            pass
        self.despachar_para_trabalhadores_livres()
        self.verificar_conclusao()

    def monitorar_heartbeats(self) -> None:
        while not self.evento_concluido.is_set():
            time.sleep(self.argumentos.intervalo_monitoramento_heartbeat)
            agora = time.perf_counter()
            expirados: List[ConexaoTrabalhador] = []
            with self.trava:
                for trabalhador in list(self.trabalhadores.values()):
                    if agora - trabalhador.ultimo_heartbeat > self.argumentos.timeout_heartbeat:
                        expirados.append(trabalhador)
            for trabalhador in expirados:
                atraso = agora - trabalhador.ultimo_heartbeat
                self.remover_trabalhador(trabalhador, f'heartbeat ausente há {atraso:.1f}s')

    def despachar_para_trabalhadores_livres(self) -> None:
        with self.trava:
            trabalhadores_livres = [t for t in self.trabalhadores.values() if not t.ocupado and not t.desconectado]
        for trabalhador in trabalhadores_livres:
            self.despachar_se_possivel(trabalhador)

    def verificar_conclusao(self) -> None:
        with self.trava:
            algum_ocupado = any(t.ocupado for t in self.trabalhadores.values())
            if not self.existe_trabalho_pendente() and not algum_ocupado and not self.tarefas:
                self.evento_concluido.set()

    def executar(self) -> None:
        self.preparar_blocos()
        servidor = self.iniciar_servidor()
        thread_aceitacao = threading.Thread(target=self.aceitar_trabalhadores, args=(servidor,), daemon=True)
        thread_monitoramento = threading.Thread(target=self.monitorar_heartbeats, daemon=True)
        thread_aceitacao.start()
        thread_monitoramento.start()
        self.aguardar_trabalhadores_iniciais()
        inicio_tempo = time.perf_counter()
        with self.trava:
            self.processamento_iniciado = True
            trabalhadores_iniciais = list(self.trabalhadores.values())
        for trabalhador in trabalhadores_iniciais:
            self.despachar_se_possivel(trabalhador)
        self.verificar_conclusao()
        self.evento_concluido.wait()
        segundos_totais = time.perf_counter() - inicio_tempo
        self.armazenamento.finalizar_execucao(self.id_execucao, segundos_totais, self.total_primos)
        thread_aceitacao.join(timeout=2.0)
        thread_monitoramento.join(timeout=2.0)
        with self.trava:
            trabalhadores_registrados = list(self.trabalhadores.values())
        for trabalhador in trabalhadores_registrados:
            try:
                self.enviar_para_trabalhador(trabalhador, {'tipo': 'encerrar'})
                trabalhador.conexao.close()
            except OSError:
                pass
        servidor.close()
        print(f'[mestre] execução finalizada. id_execucao={self.id_execucao} total_primos={self.total_primos} tempo={segundos_totais:.4f}s números={self.total_numeros_processados}')
        self.armazenamento.fechar()


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Mestre para escalonamento paralelo de intervalos de primos.')
    parser.add_argument('--endereco', dest='endereco', default='0.0.0.0')
    parser.add_argument('--porta', dest='porta', type=int, default=9000)
    parser.add_argument('--max-trabalhadores', dest='max_trabalhadores', type=int, default=30, help='quantidade máxima de trabalhadores aceitos pelo mestre; limite permitido: 1 a 30')
    parser.add_argument('--min-trabalhadores', dest='min_trabalhadores', type=int, default=1, help='quantidade mínima de trabalhadores para iniciar a execução')
    parser.add_argument('--tempo-espera-trabalhadores', dest='tempo_espera_trabalhadores', type=float, default=30.0, help='segundos de espera antes de iniciar após atingir o mínimo de trabalhadores; depois disso, novas conexões ainda são aceitas enquanto houver trabalho pendente')
    parser.add_argument('--timeout-heartbeat', dest='timeout_heartbeat', type=float, default=180.0, help='tempo máximo, em segundos, sem heartbeat antes de desconectar um trabalhador; padrão: 180 segundos')
    parser.add_argument('--intervalo-monitoramento-heartbeat', dest='intervalo_monitoramento_heartbeat', type=float, default=5.0, help='intervalo, em segundos, entre verificações de heartbeat no mestre')
    parser.add_argument('--inicio', dest='inicio', type=int, required=True)
    parser.add_argument('--fim', dest='fim', type=int, required=True)
    parser.add_argument('--modo', dest='modo', choices=['estatico', 'adaptativo'], default='adaptativo')
    parser.add_argument('--tamanho-bloco-base', dest='tamanho_bloco_base', type=int, default=10000)
    parser.add_argument('--ordem-blocos', dest='ordem_blocos', choices=['ordenado', 'embaralhado', 'intercalado'], default='intercalado')
    parser.add_argument('--semente', dest='semente', type=int, default=42)
    parser.add_argument('--janela-inicial', dest='janela_inicial', type=float, default=2.0, help='quantidade inicial de blocos enviados por tarefa para cada trabalhador')
    parser.add_argument('--janela-minima', dest='janela_minima', type=float, default=1.0)
    parser.add_argument('--janela-maxima', dest='janela_maxima', type=float, default=64.0)
    parser.add_argument('--passo-aditivo', dest='passo_aditivo', type=float, default=1.0)
    parser.add_argument('--fator-reducao', dest='fator_reducao', type=float, default=0.5)
    parser.add_argument('--tempo-alvo', dest='tempo_alvo', type=float, default=0.5)
    parser.add_argument('--calibrado', dest='calibrado', action='store_true')
    parser.add_argument('--banco', dest='banco', default='resultados.db')
    return parser


def normalizar_argumentos(argumentos: argparse.Namespace) -> argparse.Namespace:
    return argumentos


def main() -> None:
    argumentos = normalizar_argumentos(criar_parser().parse_args())
    if argumentos.fim < argumentos.inicio:
        raise SystemExit('--fim deve ser maior ou igual a --inicio')
    if argumentos.max_trabalhadores < 1 or argumentos.max_trabalhadores > 30:
        raise SystemExit('--max-trabalhadores deve estar entre 1 e 30')
    if argumentos.min_trabalhadores < 1 or argumentos.min_trabalhadores > argumentos.max_trabalhadores:
        raise SystemExit('--min-trabalhadores deve estar entre 1 e --max-trabalhadores')
    if argumentos.tempo_espera_trabalhadores < 0:
        raise SystemExit('--tempo-espera-trabalhadores deve ser maior ou igual a zero')
    if argumentos.timeout_heartbeat <= 0:
        raise SystemExit('--timeout-heartbeat deve ser maior que zero')
    if argumentos.intervalo_monitoramento_heartbeat <= 0:
        raise SystemExit('--intervalo-monitoramento-heartbeat deve ser maior que zero')
    Mestre(argumentos).executar()


if __name__ == '__main__':
    main()

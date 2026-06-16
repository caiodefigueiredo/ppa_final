import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

ESQUEMA = """
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
"""


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
        return int(cursor.lastrowid) #type: ignore

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

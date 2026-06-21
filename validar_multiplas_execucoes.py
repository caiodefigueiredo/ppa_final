import sqlite3
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print('uso: python3 validar_multiplas_execucoes.py CAMINHO_BANCO', file=sys.stderr)
        return 2

    caminho_banco = Path(sys.argv[1])
    conexao = sqlite3.connect(caminho_banco)

    colunas_execucoes = {linha[1] for linha in conexao.execute('PRAGMA table_info(execucoes)').fetchall()}
    if 'tamanho_bloco_base' not in colunas_execucoes or 'tempo_alvo' not in colunas_execucoes:
        print('ERRO: tabela execucoes não contém tamanho_bloco_base e tempo_alvo.', file=sys.stderr)
        return 1

    info_tarefas = conexao.execute('PRAGMA table_info(tarefas)').fetchall()
    chave_tarefas = {linha[1]: linha[5] for linha in info_tarefas if linha[5] > 0}
    if chave_tarefas.get('id_execucao') != 1 or chave_tarefas.get('id_tarefa') != 2:
        print(f'ERRO: chave primária de tarefas inesperada: {chave_tarefas}', file=sys.stderr)
        return 1

    execucoes = conexao.execute(
        'SELECT id_execucao, tamanho_bloco_base, tempo_alvo, total_primos FROM execucoes ORDER BY id_execucao'
    ).fetchall()
    if len(execucoes) < 2:
        print(f'ERRO: esperado pelo menos 2 execuções, obtido {len(execucoes)}.', file=sys.stderr)
        return 1

    if not all(linha[1] is not None and linha[2] is not None for linha in execucoes):
        print(f'ERRO: há execuções sem tamanho_bloco_base ou tempo_alvo: {execucoes}', file=sys.stderr)
        return 1

    tarefas_por_execucao = conexao.execute(
        'SELECT id_execucao, COUNT(*) FROM tarefas GROUP BY id_execucao ORDER BY id_execucao'
    ).fetchall()
    ids_com_tarefas = {linha[0] for linha in tarefas_por_execucao if linha[1] > 0}
    ids_execucoes = {linha[0] for linha in execucoes}
    if not ids_execucoes.issubset(ids_com_tarefas):
        print(f'ERRO: nem todas as execuções têm tarefas preservadas: {tarefas_por_execucao}', file=sys.stderr)
        return 1

    total_tarefas = conexao.execute('SELECT COUNT(*) FROM tarefas').fetchone()[0]
    conexao.close()

    print('Validação concluída com sucesso.')
    print(f'Execuções: {execucoes}')
    print(f'Tarefas por execução: {tarefas_por_execucao}')
    print(f'Total de tarefas: {total_tarefas}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

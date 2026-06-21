import sqlite3
import sys

banco = sys.argv[1]
con = sqlite3.connect(banco)
trabalhadores = con.execute(
    'select id_trabalhador, tarefas_concluidas, numeros_processados, primos_encontrados '
    'from trabalhadores order by id_trabalhador'
).fetchall()
execucao = con.execute(
    'select total_primos, total_numeros from execucoes order by id_execucao desc limit 1'
).fetchone()
print('trabalhadores=', trabalhadores)
print('execucao=', execucao)
ids = {linha[0] for linha in trabalhadores}
if 'trabalhador-inicial' not in ids or 'trabalhador-tardio' not in ids:
    raise SystemExit('falha: nem todos os trabalhadores foram registrados')
if not any(linha[0] == 'trabalhador-tardio' and linha[1] > 0 and linha[2] > 0 for linha in trabalhadores):
    raise SystemExit('falha: trabalhador tardio não recebeu tarefas')
if execucao is None or execucao[0] != 148933 or execucao[1] != 2000000:
    raise SystemExit(f'falha: resultado inesperado da execução: {execucao}')
print('teste dinamico aprovado')

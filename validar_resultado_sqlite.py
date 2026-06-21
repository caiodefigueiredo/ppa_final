import sqlite3

CAMINHO_BANCO = '/tmp/escalonamento_validacao.db'

conn = sqlite3.connect(CAMINHO_BANCO)
row = conn.execute('SELECT total_primos, total_numeros FROM execucoes ORDER BY id_execucao DESC LIMIT 1').fetchone()
cols = [r[1] for r in conn.execute('PRAGMA table_info(tarefas)').fetchall()]
conn.close()

print({'total_primos': row[0], 'total_numeros': row[1], 'tem_custo_estimado': 'custo_estimado' in cols})
if row[0] != 669 or row[1] != 5000 or 'custo_estimado' in cols:
    raise SystemExit(1)

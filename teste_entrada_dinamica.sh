#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/escalonamento_tcp_primos

PORT=9322
BANCO=/tmp/teste_dinamico.db
LOG_MESTRE=/tmp/mestre_dinamico.log
LOG_TRAB1=/tmp/trabalhador_dinamico_1.log
LOG_TRAB2=/tmp/trabalhador_dinamico_2.log

rm -f "$BANCO" "$LOG_MESTRE" "$LOG_TRAB1" "$LOG_TRAB2"

python3 src/mestre.py \
  --endereco 127.0.0.1 \
  --porta "$PORT" \
  --max-trabalhadores 30 \
  --min-trabalhadores 1 \
  --tempo-espera-trabalhadores 0 \
  --inicio 1 \
  --fim 2000000 \
  --modo adaptativo \
  --modo-unidade blocos \
  --tamanho-bloco-base 10000 \
  --tempo-alvo 0.05 \
  --banco "$BANCO" > "$LOG_MESTRE" 2>&1 &
PID_MESTRE=$!

sleep 0.4
python3 src/trabalhador.py \
  --endereco-mestre 127.0.0.1 \
  --porta-mestre "$PORT" \
  --id-trabalhador trabalhador-inicial \
  --nucleos 1 > "$LOG_TRAB1" 2>&1 &
PID_TRAB1=$!

sleep 0.6
python3 src/trabalhador.py \
  --endereco-mestre 127.0.0.1 \
  --porta-mestre "$PORT" \
  --id-trabalhador trabalhador-tardio \
  --nucleos 1 > "$LOG_TRAB2" 2>&1 &
PID_TRAB2=$!

wait "$PID_MESTRE"
wait "$PID_TRAB1" || true
wait "$PID_TRAB2" || true

python3 /home/ubuntu/escalonamento_tcp_primos/verificar_teste_dinamico.py "$BANCO"

echo '--- LOG MESTRE ---'
tail -n 80 "$LOG_MESTRE"
echo '--- LOG TRABALHADOR INICIAL ---'
tail -n 30 "$LOG_TRAB1"
echo '--- LOG TRABALHADOR TARDIO ---'
tail -n 30 "$LOG_TRAB2"

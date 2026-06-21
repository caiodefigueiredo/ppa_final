import argparse
import html
import sqlite3
from pathlib import Path


LARGURA = 1000
ALTURA = 520
MARGEM_ESQUERDA = 90
MARGEM_DIREITA = 40
MARGEM_SUPERIOR = 70
MARGEM_INFERIOR = 115
COR_TEXTO = '#1f2937'
COR_EIXO = '#374151'
COR_GRADE = '#e5e7eb'
CORES_SERIES = ['#2563eb', '#059669', '#dc2626', '#7c3aed', '#ea580c', '#0891b2', '#be123c', '#4d7c0f']


def escapar(valor) -> str:
    return html.escape(str(valor), quote=True)


def formatar_numero(valor: float) -> str:
    if abs(valor) >= 1000:
        return f'{valor:,.0f}'.replace(',', '.')
    if abs(valor) >= 10:
        return f'{valor:.1f}'.replace('.', ',')
    return f'{valor:.2f}'.replace('.', ',')


def abreviar_rotulo(rotulo: str, limite: int = 18) -> str:
    return rotulo if len(rotulo) <= limite else rotulo[: limite - 1] + '…'


def cabecalho_svg(titulo: str, subtitulo: str = '') -> list[str]:
    linhas = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{LARGURA}" height="{ALTURA}" viewBox="0 0 {LARGURA} {ALTURA}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{LARGURA / 2}" y="34" text-anchor="middle" font-family="Arial, sans-serif" font-size="24" font-weight="700" fill="{COR_TEXTO}">{escapar(titulo)}</text>',
    ]
    if subtitulo:
        linhas.append(f'<text x="{LARGURA / 2}" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#6b7280">{escapar(subtitulo)}</text>')
    return linhas


def rodape_svg(linhas: list[str]) -> str:
    linhas.append('</svg>')
    return '\n'.join(linhas) + '\n'


def desenhar_eixos(linhas: list[str], maximo: float, rotulo_y: str, rotulo_x: str) -> None:
    area_largura = LARGURA - MARGEM_ESQUERDA - MARGEM_DIREITA
    area_altura = ALTURA - MARGEM_SUPERIOR - MARGEM_INFERIOR
    x0 = MARGEM_ESQUERDA
    y0 = ALTURA - MARGEM_INFERIOR
    linhas.append(f'<line x1="{x0}" y1="{MARGEM_SUPERIOR}" x2="{x0}" y2="{y0}" stroke="{COR_EIXO}" stroke-width="1.5"/>')
    linhas.append(f'<line x1="{x0}" y1="{y0}" x2="{x0 + area_largura}" y2="{y0}" stroke="{COR_EIXO}" stroke-width="1.5"/>')
    for indice in range(6):
        valor = maximo * indice / 5
        y = y0 - (valor / maximo * area_altura if maximo else 0)
        linhas.append(f'<line x1="{x0}" y1="{y:.2f}" x2="{x0 + area_largura}" y2="{y:.2f}" stroke="{COR_GRADE}" stroke-width="1"/>')
        linhas.append(f'<text x="{x0 - 10}" y="{y + 4:.2f}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#4b5563">{formatar_numero(valor)}</text>')
    linhas.append(f'<text x="{LARGURA / 2}" y="{ALTURA - 18}" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" fill="{COR_TEXTO}">{escapar(rotulo_x)}</text>')
    linhas.append(f'<text x="18" y="{MARGEM_SUPERIOR + area_altura / 2}" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" fill="{COR_TEXTO}" transform="rotate(-90 18 {MARGEM_SUPERIOR + area_altura / 2})">{escapar(rotulo_y)}</text>')


def salvar_grafico_barras(caminho: Path, titulo: str, rotulos: list[str], valores: list[float], rotulo_y: str, rotulo_x: str) -> None:
    linhas = cabecalho_svg(titulo)
    maximo = max(max(valores), 1) * 1.12 if valores else 1
    desenhar_eixos(linhas, maximo, rotulo_y, rotulo_x)
    area_largura = LARGURA - MARGEM_ESQUERDA - MARGEM_DIREITA
    area_altura = ALTURA - MARGEM_SUPERIOR - MARGEM_INFERIOR
    y0 = ALTURA - MARGEM_INFERIOR
    largura_faixa = area_largura / max(len(valores), 1)
    largura_barra = max(12, min(55, largura_faixa * 0.62))
    for indice, (rotulo, valor) in enumerate(zip(rotulos, valores)):
        x = MARGEM_ESQUERDA + indice * largura_faixa + (largura_faixa - largura_barra) / 2
        altura = valor / maximo * area_altura if maximo else 0
        y = y0 - altura
        cor = CORES_SERIES[indice % len(CORES_SERIES)]
        linhas.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{largura_barra:.2f}" height="{altura:.2f}" fill="{cor}"/>')
        linhas.append(f'<text x="{x + largura_barra / 2:.2f}" y="{y - 7:.2f}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="{COR_TEXTO}">{formatar_numero(valor)}</text>')
        linhas.append(f'<text x="{x + largura_barra / 2:.2f}" y="{y0 + 18}" text-anchor="end" font-family="Arial, sans-serif" font-size="11" fill="#4b5563" transform="rotate(-35 {x + largura_barra / 2:.2f} {y0 + 18})">{escapar(abreviar_rotulo(rotulo))}</text>')
    caminho.write_text(rodape_svg(linhas), encoding='utf-8')


def salvar_grafico_linhas(
    caminho: Path,
    titulo: str,
    series: dict[str, list[tuple[float, float]]],
    rotulo_y: str,
    rotulo_x: str,
    minimo_x_fixo: float | None = None,
    maximo_x_fixo: float | None = None,
    maximo_y_fixo: float | None = None,
    raio_ponto: float = 4.0,
) -> None:
    todos_pontos = [ponto for pontos in series.values() for ponto in pontos]
    linhas = cabecalho_svg(titulo)
    if not todos_pontos:
        caminho.write_text(rodape_svg(linhas), encoding='utf-8')
        return
    xs = [ponto[0] for ponto in todos_pontos]
    ys = [ponto[1] for ponto in todos_pontos]
    min_x = float(minimo_x_fixo) if minimo_x_fixo is not None else min(xs)
    max_x = float(maximo_x_fixo) if maximo_x_fixo is not None else max(xs)
    max_y = float(maximo_y_fixo) if maximo_y_fixo is not None else max(max(ys), 1) * 1.12
    desenhar_eixos(linhas, max_y, rotulo_y, rotulo_x)
    area_largura = LARGURA - MARGEM_ESQUERDA - MARGEM_DIREITA
    area_altura = ALTURA - MARGEM_SUPERIOR - MARGEM_INFERIOR
    y0 = ALTURA - MARGEM_INFERIOR

    def escala_x(valor: float) -> float:
        if max_x == min_x:
            return MARGEM_ESQUERDA + area_largura / 2
        return MARGEM_ESQUERDA + (valor - min_x) / (max_x - min_x) * area_largura

    def escala_y(valor: float) -> float:
        return y0 - (valor / max_y * area_altura if max_y else 0)

    for indice, (nome, pontos) in enumerate(series.items()):
        cor = CORES_SERIES[indice % len(CORES_SERIES)]
        pontos_ordenados = sorted(pontos)
        sequencia = ' '.join(f'{escala_x(x):.2f},{escala_y(y):.2f}' for x, y in pontos_ordenados)
        linhas.append(f'<polyline points="{sequencia}" fill="none" stroke="{cor}" stroke-width="0.3"/>')
        for x, y in pontos_ordenados:
            linhas.append(f'<circle cx="{escala_x(x):.2f}" cy="{escala_y(y):.2f}" r="{raio_ponto:.2f}" fill="{cor}"/>')
        y_legenda = MARGEM_SUPERIOR + 18 + indice * 22
        x_legenda = LARGURA - 260
        linhas.append(f'<rect x="{x_legenda}" y="{y_legenda - 10}" width="14" height="14" fill="{cor}"/>')
        linhas.append(f'<text x="{x_legenda + 22}" y="{y_legenda + 2}" font-family="Arial, sans-serif" font-size="12" fill="{COR_TEXTO}">{escapar(nome)}</text>')

    for indice in range(6):
        valor = min_x + (max_x - min_x) * indice / 5 if max_x != min_x else min_x
        x = escala_x(valor)
        linhas.append(f'<text x="{x:.2f}" y="{y0 + 18}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#4b5563">{formatar_numero(valor)}</text>')
    caminho.write_text(rodape_svg(linhas), encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description='Gera gráficos SVG simples a partir do SQLite, usando somente a biblioteca padrão.')
    parser.add_argument('--banco', dest='banco', default='resultados.db')
    parser.add_argument('--saida', dest='saida', default='graficos')
    argumentos = parser.parse_args()

    saida = Path(argumentos.saida)
    saida.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(argumentos.banco)

    execucoes = conexao.execute('SELECT id_execucao, modo, segundos_totais, vazao_numeros_por_segundo FROM execucoes ORDER BY id_execucao').fetchall()
    if execucoes:
        rotulos = [f'{linha[0]}-{linha[1]}' for linha in execucoes]
        tempos = [float(linha[2] or 0.0) for linha in execucoes]
        salvar_grafico_barras(saida / 'tempo_total.svg', 'Comparação de tempo total por execução', rotulos, tempos, 'Tempo total (s)', 'Execução')

        vazoes = [float(linha[3] or 0.0) for linha in execucoes]
        salvar_grafico_barras(saida / 'throughput.svg', 'Throughput por execução', rotulos, vazoes, 'Números processados por segundo', 'Execução')

    tarefas = conexao.execute(
        'SELECT id_execucao, id_tarefa, id_trabalhador, janela_antes, janela_depois '
        'FROM tarefas WHERE janela_antes IS NOT NULL ORDER BY id_execucao, id_tarefa'
    ).fetchall()
    if tarefas:
        ids_execucao = sorted({int(linha[0]) for linha in tarefas})
        for id_execucao in ids_execucao:
            por_trabalhador: dict[str, list[tuple[float, float]]] = {}
            for linha_execucao, id_tarefa, id_trabalhador, antes, depois in tarefas:
                if int(linha_execucao) != id_execucao:
                    continue
                por_trabalhador.setdefault(str(id_trabalhador), []).append((float(id_tarefa), float(depois or 0.0)))
            salvar_grafico_linhas(
                saida / f'evolucao_janela_execucao_{id_execucao}.svg',
                f'Evolução da janela adaptativa - execução {id_execucao}',
                por_trabalhador,
                'Janela após ajuste',
                'Tarefa',
                minimo_x_fixo=0.0,
                maximo_x_fixo=650.0,
                maximo_y_fixo=100.0,
                raio_ponto=0.7,
            )

    linhas_trabalhadores = conexao.execute('SELECT id_execucao, id_trabalhador, numeros_processados, total_segundos_trabalhador FROM trabalhadores ORDER BY id_execucao, id_trabalhador').fetchall()
    if linhas_trabalhadores:
        rotulos = [f'{linha[0]}-{linha[1]}' for linha in linhas_trabalhadores]
        numeros = [float(linha[2] or 0.0) for linha in linhas_trabalhadores]
        salvar_grafico_barras(saida / 'carga_por_trabalhador.svg', 'Distribuição de carga por trabalhador', rotulos, numeros, 'Números processados', 'Trabalhador')

    conexao.close()
    print(f'Gráficos SVG salvos em: {saida.resolve()}')


if __name__ == '__main__':
    main()

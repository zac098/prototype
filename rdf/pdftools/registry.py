"""Catálogo das ferramentas: o que cada uma pede ao usuário e qual operação executa.

A interface lê este catálogo e monta a tela de cada ferramenta sozinha. Para criar uma ferramenta nova,
basta escrever a operação em ops.py e acrescentar um Tool aqui.

Modos de saída (Tool.mode):
- "combine": vários arquivos viram um só (o usuário escolhe onde salvar o arquivo)
- "each":    cada arquivo gera um arquivo (um arquivo: escolhe o nome; vários: escolhe a pasta)
- "multi":   cada arquivo gera vários (os arquivos vão para uma subpasta nova, escolhida a pasta pai)
"""

import unicodedata
from dataclasses import dataclass, field
from typing import Callable

from rdf.pdftools import ops

# Categorias, na ordem em que aparecem na tela inicial.
CATEGORIES = ('Folha de ponto', 'Organizar', 'Otimizar', 'Converter', 'Editar', 'Segurança')

# Ícone de cada ferramenta: código da fonte Segoe MDL2 Assets (já vem no Windows 10 e 11).
# Se a fonte faltar, a interface usa o símbolo simples (Tool.glyph).
TOOL_ICONS = {
    'renamer': 'E8AC',
    'merge': 'E710',
    'split': 'E8C6',
    'remove': 'E74D',
    'extract': 'E8A7',
    'organize': 'E8CB',
    'compress': 'E73F',
    'repair': 'E90F',
    'ocr': 'E8FE',
    'images-to-pdf': 'E8B9',
    'pdf-to-images': 'E91B',
    'rotate': 'E7AD',
    'crop': 'E7A8',
    'page-numbers': 'E9D5',
    'watermark': 'E8D2',
    'protect': 'E72E',
    'unlock': 'E785',
    'redact': 'ED1A',
    'metadata': 'E946',
    'pdf-to-text': 'E8A5',
    'grayscale': 'E790',
    'n-up': 'E80A',
    'fit-paper': 'E740',
}


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    kind: str  # text | choice | int | bool | password
    default: object = None
    choices: tuple = ()
    help: str = ''
    # Só mostra a opção quando outra tem determinado valor: ("mode", "Personalizada")
    visible_if: tuple = ()


@dataclass(frozen=True)
class Tool:
    id: str
    title: str
    description: str
    category: str
    glyph: str
    mode: str = 'each'
    inputs: str = 'pdf'  # pdf | image
    multiple: bool = True
    min_files: int = 1
    suffix: str = ''  # "_comprimido" -> nome-sugerido_comprimido.pdf
    action: str = 'Executar'
    options: tuple = ()
    run: Callable = field(default=None, repr=False)
    keywords: str = ''
    special: bool = False  # abre uma tela própria (Renomear folhas de ponto), sem o formulário padrão
    ordered: bool = False  # a ordem da lista importa (mostra as setas para subir e descer)
    any_format: bool = True  # aceita também imagens, texto, HTML e Office (convertidos para PDF); False: só PDF
    output_ext: str = 'pdf'  # extensão do que a ferramenta grava (pdf, ou txt em "PDF para texto")
    # Escolha de páginas por miniaturas, ligada a uma opção de texto: ("select" ou "order", chave da opção)
    page_picker: tuple = ()

    @property
    def icon(self):
        return TOOL_ICONS.get(self.id, '')


def _tool(id, title, description, category, glyph, run, **kwargs):
    return Tool(id=id, title=title, description=description, category=category, glyph=glyph, run=run, **kwargs)


def _run_merge(sources, dest, o, progress):
    return ops.merge_pdfs(sources, dest, progress)


def _run_split(source, dest, o, progress):
    mode = {'Por intervalos': 'ranges', 'A cada N páginas': 'every'}.get(o['mode'], 'each')
    return ops.split_pdf(source, dest, mode, o['ranges'], o['every'], progress)


def _run_remove(source, dest, o, progress):
    return ops.select_pages(source, dest, o['pages'], keep=False, progress=progress)


def _run_extract(source, dest, o, progress):
    return ops.select_pages(source, dest, o['pages'], keep=True, progress=progress)


def _run_organize(source, dest, o, progress):
    mode = 'reverse' if o['mode'] == 'Inverter a ordem' else 'custom'
    return ops.reorder_pages(source, dest, mode, o['order'], progress)


def _run_compress(source, dest, o, progress):
    return ops.compress_pdf(source, dest, o['level'], progress)


def _run_repair(source, dest, o, progress):
    return ops.repair_pdf(source, dest, progress)


def _run_ocr(source, dest, o, progress):
    dpi = 300 if o['quality'].startswith('Alta') else 200
    return ops.ocr_pdf(source, dest, o['language'], dpi, progress)


def _run_images_to_pdf(sources, dest, o, progress):
    return ops.images_to_pdf(sources, dest, o['page_size'], o['orientation'], o['margin'], progress)


def _run_pdf_to_images(source, dest, o, progress):
    dpi = int(o['dpi'].split()[0])
    return ops.pdf_to_images(source, dest, o['what'], o['format'], dpi, o['pages'], progress)


def _run_rotate(source, dest, o, progress):
    spec = o['pages'] if o['scope'] == 'Só algumas páginas' else ''
    return ops.rotate_pdf(source, dest, o['angle'], spec, progress)


def _run_crop(source, dest, o, progress):
    return ops.crop_pdf(source, dest, o['top'], o['bottom'], o['left'], o['right'], progress)


def _run_numbers(source, dest, o, progress):
    return ops.add_page_numbers(source, dest, o['position'], o['style'], o['first'], o['start'], o['size'], progress)


def _run_watermark(source, dest, o, progress):
    return ops.add_watermark(source, dest, o['text'], o['size'], o['opacity'], o['angle'], o['color'], progress)


def _run_protect(source, dest, o, progress):
    return ops.protect_pdf(source, dest, o['password'], o['owner'], o['print'], o['copy'], o['edit'], progress)


def _run_unlock(source, dest, o, progress):
    return ops.unlock_pdf(source, dest, o['password'], progress)


def _run_redact(source, dest, o, progress):
    return ops.redact_pdf(source, dest, o['terms'], o['cpf'], o['cnpj'], o['email'], o['phone'], progress)


def _run_metadata(source, dest, o, progress):
    mode = 'Remover' if o['mode'].startswith('Remover') else 'Editar'
    return ops.edit_metadata(source, dest, mode, o['title'], o['author'], o['subject'], o['keywords'], progress)


def _run_pdf_to_text(source, dest, o, progress):
    return ops.pdf_to_text(source, dest, o['layout'], progress)


def _run_grayscale(source, dest, o, progress):
    return ops.grayscale_pdf(source, dest, progress)


def _run_n_up(source, dest, o, progress):
    return ops.n_up_pdf(source, dest, o['layout'], o['paper'], o['border'], progress)


def _run_fit_paper(source, dest, o, progress):
    return ops.fit_to_paper(source, dest, o['paper'], progress)


PAGES_HELP = 'Exemplos: 1-3, 5, 8-  (vírgula separa; "8-" vai até a última página)'

TOOLS = (
    Tool(
        id='renamer',
        title='Renomear folhas de ponto',
        description='Lê matrícula, nome e mês de folhas de ponto, atestados e declarações e renomeia os arquivos.',
        category='Folha de ponto',
        glyph='Aa',
        special=True,
        keywords='rdf renomear folha ponto matricula nome ocr atestado declaracao',
    ),
    _tool(
        'merge',
        'Unir PDF',
        'Junte vários PDFs (ou fotos e documentos) em um único arquivo, na ordem que você escolher, ou imprima a lista direto pela janela de impressão do Windows.',
        'Organizar',
        '+',
        _run_merge,
        mode='combine',
        min_files=2,
        suffix='_unido',
        action='Unir PDF',
        keywords='juntar combinar mesclar merge imprimir impressao impressora print',
    ),
    _tool(
        'split',
        'Dividir PDF',
        'Separe um PDF por intervalos, a cada N páginas ou página por página.',
        'Organizar',
        '÷',
        _run_split,
        mode='multi',
        multiple=False,
        suffix='_dividido',
        action='Dividir PDF',
        keywords='separar cortar split',
        options=(
            Option(
                'mode',
                'Como dividir',
                'choice',
                'Por intervalos',
                ('Por intervalos', 'A cada N páginas', 'Uma página por arquivo'),
            ),
            Option(
                'ranges',
                'Intervalos (um arquivo para cada)',
                'text',
                '1-3, 4-6',
                help='Exemplo: 1-3, 4-6, 7-',
                visible_if=('mode', 'Por intervalos'),
            ),
            Option('every', 'Páginas por arquivo', 'int', 2, visible_if=('mode', 'A cada N páginas')),
        ),
    ),
    _tool(
        'remove',
        'Remover páginas',
        'Apague as páginas que você não quer e mantenha o resto.',
        'Organizar',
        '×',
        _run_remove,
        multiple=False,
        suffix='_sem_paginas',
        page_picker=('select', 'pages'),
        action='Remover páginas',
        keywords='excluir apagar deletar remove',
        options=(Option('pages', 'Páginas a remover', 'text', '', help=PAGES_HELP),),
    ),
    _tool(
        'extract',
        'Extrair páginas',
        'Crie um novo PDF só com as páginas que você escolher.',
        'Organizar',
        '↗',
        _run_extract,
        multiple=False,
        suffix='_extraido',
        page_picker=('select', 'pages'),
        action='Extrair páginas',
        keywords='extract selecionar',
        options=(Option('pages', 'Páginas a extrair', 'text', '', help=PAGES_HELP),),
    ),
    _tool(
        'organize',
        'Organizar páginas',
        'Mude a ordem das páginas: inverta tudo ou digite a ordem que quiser.',
        'Organizar',
        '⇅',
        _run_organize,
        multiple=False,
        suffix='_organizado',
        page_picker=('order', 'order'),
        action='Organizar PDF',
        keywords='reordenar ordem inverter organize',
        options=(
            Option('mode', 'Ordem', 'choice', 'Ordem personalizada', ('Ordem personalizada', 'Inverter a ordem')),
            Option(
                'order',
                'Nova ordem das páginas',
                'text',
                '',
                help='Ex.: 3, 1, 2, 4-6. Páginas que ficarem de fora são descartadas.',
                visible_if=('mode', 'Ordem personalizada'),
            ),
        ),
    ),
    _tool(
        'n-up',
        'Várias páginas por folha',
        'Imprima 2, 4, 6 ou 9 páginas em cada folha e economize papel.',
        'Organizar',
        '⊞',
        _run_n_up,
        suffix='_por_folha',
        action='Montar folhas',
        keywords='nup n-up economizar papel imprimir duas quatro paginas folha livreto',
        options=(
            Option('layout', 'Páginas em cada folha', 'choice', '2 por folha', tuple(ops.SHEET_LAYOUTS)),
            Option('paper', 'Papel', 'choice', 'A4', tuple(ops.PAPER_SIZES)),
            Option('border', 'Desenhar uma borda fina em cada página', 'bool', False),
        ),
    ),
    _tool(
        'compress',
        'Comprimir PDF',
        'Reduza o tamanho do arquivo mantendo a leitura confortável.',
        'Otimizar',
        '↓',
        _run_compress,
        suffix='_comprimido',
        action='Comprimir PDF',
        keywords='reduzir tamanho diminuir compress',
        options=(
            Option(
                'level',
                'Nível de compressão',
                'choice',
                'Recomendada',
                tuple(ops.COMPRESSION_LEVELS),
                help='Extrema reduz mais, mas deixa as imagens com menos qualidade.',
            ),
        ),
    ),
    _tool(
        'repair',
        'Reparar PDF',
        'Tente recuperar um PDF danificado ou que não abre direito.',
        'Otimizar',
        '✓',
        _run_repair,
        suffix='_reparado',
        any_format=False,  # reparar só faz sentido num PDF danificado
        action='Reparar PDF',
        keywords='consertar corrompido repair',
    ),
    _tool(
        'ocr',
        'OCR - PDF pesquisável',
        'Reconheça o texto de PDFs escaneados para pesquisar e copiar o conteúdo.',
        'Otimizar',
        'T',
        _run_ocr,
        suffix='_ocr',
        action='Reconhecer texto',
        keywords='ocr escaneado pesquisavel reconhecer texto tesseract',
        options=(
            Option('language', 'Idioma do documento', 'choice', 'Português + Inglês', tuple(ops.OCR_LANGUAGES)),
            Option(
                'quality', 'Qualidade', 'choice', 'Normal (mais rápido)', ('Normal (mais rápido)', 'Alta (mais lento)')
            ),
        ),
    ),
    _tool(
        'images-to-pdf',
        'Imagem para PDF',
        'Transforme JPG, PNG e outras imagens em um PDF.',
        'Converter',
        'JPG',
        _run_images_to_pdf,
        mode='combine',
        inputs='image',
        suffix='_imagens',
        action='Criar PDF',
        keywords='jpg png foto imagem converter para pdf',
        options=(
            Option('page_size', 'Tamanho da página', 'choice', 'A4', tuple(ops.PAGE_SIZES)),
            Option(
                'orientation',
                'Orientação',
                'choice',
                'Automática',
                ('Automática', 'Retrato', 'Paisagem'),
                visible_if=('page_size', ('A4', 'Carta')),
            ),
            Option('margin', 'Margem', 'choice', 'Pequena', tuple(ops.MARGINS)),
        ),
    ),
    _tool(
        'pdf-to-images',
        'PDF para imagem',
        'Converta as páginas em JPG ou PNG, ou extraia as imagens do PDF.',
        'Converter',
        'PDF',
        _run_pdf_to_images,
        mode='multi',
        suffix='_imagens',
        action='Converter',
        keywords='jpg png converter imagem extrair',
        options=(
            Option(
                'what',
                'O que fazer',
                'choice',
                'Páginas como imagens',
                ('Páginas como imagens', 'Extrair imagens do PDF'),
            ),
            Option('format', 'Formato', 'choice', 'JPG', ('JPG', 'PNG'), visible_if=('what', 'Páginas como imagens')),
            Option(
                'dpi',
                'Qualidade',
                'choice',
                '150 dpi (equilibrada)',
                ('72 dpi (rascunho)', '150 dpi (equilibrada)', '300 dpi (alta)'),
                visible_if=('what', 'Páginas como imagens'),
            ),
            Option(
                'pages',
                'Só estas páginas (opcional)',
                'text',
                '',
                help='Deixe em branco para converter todas. ' + PAGES_HELP,
                visible_if=('what', 'Páginas como imagens'),
            ),
        ),
    ),
    _tool(
        'pdf-to-text',
        'PDF para texto',
        'Extraia o texto do PDF para um arquivo .txt que abre em qualquer programa.',
        'Converter',
        'TXT',
        _run_pdf_to_text,
        suffix='',
        output_ext='txt',
        action='Extrair texto',
        keywords='txt texto extrair copiar converter bloco de notas',
        options=(
            Option(
                'layout',
                'Formato do texto',
                'choice',
                'Texto corrido',
                ('Texto corrido', 'Manter a disposição'),
                help='"Manter a disposição" preserva colunas e espaços (bom para tabelas).',
            ),
        ),
    ),
    _tool(
        'rotate',
        'Girar PDF',
        'Gire todas as páginas ou só algumas.',
        'Editar',
        '↻',
        _run_rotate,
        suffix='_girado',
        action='Girar PDF',
        keywords='rotacionar virar girar rotate',
        options=(
            Option('angle', 'Girar', 'choice', '90° para a direita', tuple(ops.ROTATIONS)),
            Option('scope', 'Quais páginas', 'choice', 'Todas as páginas', ('Todas as páginas', 'Só algumas páginas')),
            Option('pages', 'Páginas', 'text', '', help=PAGES_HELP, visible_if=('scope', 'Só algumas páginas')),
        ),
    ),
    _tool(
        'crop',
        'Cortar margens',
        'Corte as bordas de todas as páginas (medidas em milímetros).',
        'Editar',
        '✂',
        _run_crop,
        suffix='_cortado',
        action='Cortar PDF',
        keywords='recortar margens crop',
        options=(
            Option('top', 'Em cima (mm)', 'int', 10),
            Option('bottom', 'Embaixo (mm)', 'int', 10),
            Option('left', 'Esquerda (mm)', 'int', 10),
            Option('right', 'Direita (mm)', 'int', 10),
        ),
    ),
    _tool(
        'page-numbers',
        'Números de página',
        'Numere as páginas do PDF onde e como você quiser.',
        'Editar',
        '1',
        _run_numbers,
        suffix='_numerado',
        action='Adicionar números',
        keywords='numerar paginar numeracao',
        options=(
            Option('position', 'Posição', 'choice', 'Inferior centralizado', ops.NUMBER_POSITIONS),
            Option('style', 'Formato', 'choice', 'Página 1 de N', ops.NUMBER_FORMATS),
            Option('first', 'Primeiro número', 'int', 1),
            Option('start', 'Começar na página', 'int', 1),
            Option('size', 'Tamanho da letra', 'int', 10),
        ),
    ),
    _tool(
        'watermark',
        'Marca d\'água',
        'Escreva um texto (como CONFIDENCIAL) sobre todas as páginas.',
        'Editar',
        'W',
        _run_watermark,
        suffix='_marca_dagua',
        action='Aplicar marca d\'água',
        keywords='marca dagua texto confidencial watermark',
        options=(
            Option('text', 'Texto', 'text', 'CONFIDENCIAL'),
            Option('angle', 'Direção', 'choice', 'Diagonal', ('Diagonal', 'Horizontal')),
            Option('color', 'Cor', 'choice', 'Cinza', tuple(ops.WATERMARK_COLORS)),
            Option('size', 'Tamanho da letra', 'int', 60),
            Option('opacity', 'Intensidade (%)', 'int', 30, help='De 5 (quase invisível) a 100 (forte).'),
        ),
    ),
    _tool(
        'grayscale',
        'Escala de cinza',
        'Converta as cores para tons de cinza, mantendo o texto pesquisável: ideal para imprimir.',
        'Editar',
        '◐',
        _run_grayscale,
        suffix='_cinza',
        action='Converter para cinza',
        keywords='preto e branco cinza grayscale monocromatico imprimir tinta cores',
    ),
    _tool(
        'fit-paper',
        'Ajustar tamanho do papel',
        'Deixe todas as páginas em A4 (ou Carta, Ofício, A3), sem distorcer o conteúdo.',
        'Editar',
        '⤢',
        _run_fit_paper,
        suffix='_ajustado',
        action='Ajustar páginas',
        keywords='redimensionar tamanho papel a4 carta oficio escala padronizar',
        options=(Option('paper', 'Papel', 'choice', 'A4', tuple(ops.PAPER_SIZES)),),
    ),
    _tool(
        'protect',
        'Proteger PDF',
        'Coloque uma senha no PDF (criptografia AES de 256 bits).',
        'Segurança',
        '●',
        _run_protect,
        suffix='_protegido',
        action='Proteger PDF',
        keywords='senha proteger criptografar protect password',
        options=(
            Option('password', 'Senha para abrir', 'password', ''),
            Option(
                'owner',
                'Senha de administrador (opcional)',
                'password',
                '',
                help='Controla as permissões abaixo. Em branco, o app cria uma que não fica guardada.',
            ),
            Option('print', 'Permitir imprimir', 'bool', True),
            Option('copy', 'Permitir copiar texto', 'bool', False),
            Option('edit', 'Permitir editar', 'bool', False),
        ),
    ),
    _tool(
        'unlock',
        'Desbloquear PDF',
        'Remova a senha e as restrições de um PDF que você tem direito de abrir.',
        'Segurança',
        '○',
        _run_unlock,
        suffix='_desbloqueado',
        any_format=False,  # só PDF tem senha de PDF
        action='Desbloquear PDF',
        keywords='senha remover desbloquear unlock password',
        options=(Option('password', 'Senha atual (se o PDF pedir)', 'password', ''),),
    ),
    _tool(
        'redact',
        'Tarjar dados (LGPD)',
        'Apague de verdade CPFs, e-mails, telefones e outros textos antes de compartilhar um PDF.',
        'Segurança',
        '▬',
        _run_redact,
        suffix='_tarjado',
        action='Tarjar e salvar',
        keywords='lgpd tarjar ocultar esconder apagar cpf cnpj email telefone dados pessoais anonimizar redact censurar',
        options=(
            Option(
                'terms',
                'Textos para tarjar (opcional)',
                'text',
                '',
                help='Separe por vírgula. Ex.: Maria da Silva, 123456. Maiúsculas e minúsculas tanto faz.',
            ),
            Option('cpf', 'Tarjar todos os CPFs', 'bool', True),
            Option('cnpj', 'Tarjar todos os CNPJs', 'bool', False),
            Option('email', 'Tarjar todos os e-mails', 'bool', False),
            Option('phone', 'Tarjar todos os telefones', 'bool', False),
        ),
    ),
    _tool(
        'metadata',
        'Metadados do PDF',
        'Veja quem criou o arquivo, edite título e autor ou remova essas informações ocultas.',
        'Segurança',
        'i',
        _run_metadata,
        suffix='_metadados',
        multiple=False,
        action='Salvar PDF',
        keywords='metadados autor titulo propriedades informacoes privacidade remover limpar lgpd xmp',
        options=(
            Option(
                'mode',
                'O que fazer',
                'choice',
                'Editar informações',
                ('Editar informações', 'Remover tudo (privacidade)'),
                help='Remover apaga autor, programa, datas, scripts e anexos. As páginas não mudam.',
            ),
            Option('title', 'Título', 'text', '', visible_if=('mode', 'Editar informações')),
            Option('author', 'Autor', 'text', '', visible_if=('mode', 'Editar informações')),
            Option('subject', 'Assunto', 'text', '', visible_if=('mode', 'Editar informações')),
            Option(
                'keywords',
                'Palavras-chave',
                'text',
                '',
                help='Campos em branco ficam como estão.',
                visible_if=('mode', 'Editar informações'),
            ),
        ),
    ),
)

TOOLS_BY_ID = {tool.id: tool for tool in TOOLS}
NEW_TOOLS = frozenset({'redact', 'metadata', 'pdf-to-text', 'grayscale', 'n-up', 'fit-paper'})  # selo "Novo"


def fold(text):
    """Texto sem acentos e em minúsculas: "Números" e "numeros" são a mesma busca."""
    decomposed = unicodedata.normalize('NFKD', text or '')
    return ''.join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def _relevance(tool, words):
    """Quanto a ferramenta combina com as palavras (0 = não combina). Título vale mais que descrição."""
    title = fold(tool.title)
    title_words = title.split()
    keywords = fold(f'{tool.keywords} {tool.category}')
    description = fold(tool.description)
    score = 0
    for word in words:
        if any(item.startswith(word) for item in title_words):
            score += 6
        elif word in title:
            score += 4
        elif any(item.startswith(word) for item in keywords.split()):
            score += 3
        elif word in keywords:
            score += 2
        elif word in description:
            score += 1
        else:
            return 0  # todas as palavras precisam aparecer em algum lugar
    return score


def search_tools(query=''):
    """Ferramentas que combinam com o texto digitado, da mais para a menos relevante.

    Sem acentos e sem diferença de maiúsculas; sem texto, todas na ordem do catálogo."""
    words = fold(query).split()
    if not words:
        return list(TOOLS)
    scored = [(_relevance(tool, words), index, tool) for index, tool in enumerate(TOOLS)]
    return [tool for score, _index, tool in sorted(scored, key=lambda item: (-item[0], item[1])) if score]

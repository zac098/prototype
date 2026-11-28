"""Autoteste do RDF: confere, sem abrir a janela, se tudo o que o app usa está presente e funcionando.

Feito para o RDF empacotado: o CI roda "RDF.exe --autoteste resultado.json" logo depois do PyInstaller. Se uma
biblioteca, um plugin do Qt, uma tela ou um arquivo do Tesseract tiver ficado de fora do executável, o autoteste falha
e a versão não é publicada. Funciona também a partir do código (python -m rdf --autoteste saida.json).

O resultado vai para o arquivo JSON (o executável não tem console) e para o código de saída: 0 deu tudo certo.
"""

import importlib
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path

FLAG = '--autoteste'
SAMPLE_TEXT = 'RDF AUTOTESTE 2026'


def _check_libraries():
    import cv2
    import fitz
    import numpy
    import PIL
    import pytesseract

    return f'PyMuPDF {fitz.VersionBind}, Pillow {PIL.__version__}, numpy {numpy.__version__}, OpenCV {cv2.__version__}, pytesseract {pytesseract.__version__}'


def _check_secure_connection():
    """A atualização baixa do GitHub por HTTPS: o executável precisa do módulo ssl e dos certificados do sistema."""
    import ssl

    context = ssl.create_default_context()
    authorities = context.cert_store_stats().get('x509_ca', 0)
    if not authorities:
        raise RuntimeError('Nenhum certificado de autoridade carregado: a atualização pelo GitHub não funcionaria')
    return f'{ssl.OPENSSL_VERSION}, {authorities} certificados de autoridade'


def _sample_image(scale=3):
    """Uma imagem (numpy RGB) com SAMPLE_TEXT em letra grande, feita pelo próprio PyMuPDF."""
    import fitz
    import numpy as np

    with fitz.open() as document:
        page = document.new_page(width=420, height=90)
        page.insert_text((20, 58), SAMPLE_TEXT, fontsize=30)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy()


def _check_tesseract():
    import pytesseract

    from rdf.core import config

    exe = config.configure_tesseract(config.app_base_dir())
    if not exe:
        raise RuntimeError('Tesseract não encontrado')
    bundle = getattr(sys, '_MEIPASS', None)
    if bundle and not Path(exe).resolve().is_relative_to(Path(bundle).resolve()):
        # No CI o Tesseract também está instalado no sistema: o do executável precisa ser o usado.
        raise RuntimeError(f'O Tesseract embutido não foi encontrado (achou outro em {exe})')
    languages = set(pytesseract.get_languages(config=''))
    missing = {'por', 'eng'} - languages
    if missing:
        raise RuntimeError(f'Idiomas do Tesseract faltando: {", ".join(sorted(missing))}')
    image = _sample_image()
    text = pytesseract.image_to_string(image, lang='por+eng', config='--psm 7', timeout=120)
    if 'AUTOTESTE' not in text.upper():
        raise RuntimeError(f'Leitura errada: {text.strip()!r}')
    data = pytesseract.image_to_data(image, lang='por+eng', config='--psm 7', output_type=pytesseract.Output.DICT)
    if not any('AUTOTESTE' in word.upper() for word in data['text']):
        raise RuntimeError('Leitura com posições (TSV) não achou o texto')
    pdf = pytesseract.image_to_pdf_or_hocr(image, lang='por', extension='pdf', timeout=120)
    if not pdf.startswith(b'%PDF'):
        raise RuntimeError('O PDF pesquisável do Tesseract veio vazio')
    return f'{exe} ({", ".join(sorted(languages))})'


def _check_pdf_tools(folder):
    import fitz
    from PIL import Image

    from rdf.core.imaging import preprocess
    from rdf.pdftools import ops, sources

    parts = []
    for number in range(2):
        path = folder / f'parte{number}.pdf'
        with fitz.open() as document:
            document.new_page().insert_text((72, 72), f'Página {number + 1}')
            document.save(path)
        parts.append(path)
    merged = folder / 'unido.pdf'
    ops.merge_pdfs(parts, merged)
    picture = folder / 'foto.png'
    Image.new('RGB', (300, 200), (200, 30, 30)).save(picture)
    converted = sources.convert_to_pdf(picture, folder / 'foto.pdf')
    compressed = folder / 'comprimido.pdf'
    ops.compress_pdf(merged, compressed)
    with fitz.open(merged) as document, fitz.open(converted) as photo:
        if document.page_count != 2 or photo.page_count != 1:
            raise RuntimeError('Unir ou converter gerou páginas erradas')
    binary = preprocess(_sample_image(scale=1))  # OpenCV de verdade (a mesma preparação da leitura das folhas)
    if binary is None or binary.size == 0:
        raise RuntimeError('O OpenCV não preparou a imagem')
    return 'unir, converter imagem, comprimir e preparar imagem para OCR'


def _check_interface():
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import QCoreApplication, qVersion
    from PySide6.QtGui import QIcon

    from rdf.core.config import resource_path
    from rdf.pdftools.registry import TOOLS
    from rdf.qt import __main__ as entry
    from rdf.qt.window import MainWindow, page_class

    app = entry.create_app([sys.argv[0]])
    if QCoreApplication.translate('QPlatformTheme', '&Yes') != '&Sim':
        raise RuntimeError('Tradução do Qt para português não carregou')
    if QIcon(str(resource_path('assets', 'icone.ico'))).isNull():
        raise RuntimeError('Ícone do app não carregou (plugin de imagens do Qt)')
    for name in entry.PRELOAD_MODULES:  # importados por nome: o PyInstaller não os vê sozinho
        importlib.import_module(name)
    screens = sorted({page_class(tool).__name__ for tool in TOOLS})
    window = MainWindow()
    for tool_id in ('merge', 'compress', 'renamer'):
        window.open_tool(tool_id)
        window.reset_tool(tool_id)
    window.deleteLater()
    app.processEvents()
    return f'Qt {qVersion()} (PySide6 {pyside_version}), telas: {", ".join(screens)}'


CHECKS = (
    ('bibliotecas', _check_libraries),
    ('conexão segura', _check_secure_connection),
    ('tesseract', _check_tesseract),
    ('ferramentas de PDF', None),  # recebe a pasta temporária
    ('interface', _check_interface),
)


def run():
    """Roda todas as conferências. Devolve o relatório (dicionário pronto para JSON)."""
    from rdf import APP_VERSION

    started = time.monotonic()
    report = {'versao': APP_VERSION, 'empacotado': bool(getattr(sys, 'frozen', False)), 'verificacoes': []}
    with tempfile.TemporaryDirectory(prefix='rdf-autoteste-') as tmp:
        for name, check in CHECKS:
            item = {'nome': name}
            try:
                item['detalhe'] = check() if check is not None else _check_pdf_tools(Path(tmp))
                item['ok'] = True
            except Exception as exc:  # o relatório mostra tudo o que falhou, não só o primeiro erro
                item['ok'] = False
                item['detalhe'] = f'{type(exc).__name__}: {exc}'
                item['rastro'] = traceback.format_exc(limit=8)
            report['verificacoes'].append(item)
    report['ok'] = all(item['ok'] for item in report['verificacoes'])
    report['segundos'] = round(time.monotonic() - started, 1)
    return report


def main(argv):
    """python -m rdf --autoteste [arquivo.json]. Código de saída 0 se tudo funcionou."""
    args = list(argv)
    position = args.index(FLAG)
    output = Path(args[position + 1]) if len(args) > position + 1 else Path('rdf-autoteste.json')
    report = run()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['ok'] else 1

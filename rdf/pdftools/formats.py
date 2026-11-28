"""Formatos de arquivo que o RDF aceita, num módulo leve.

Quem só precisa saber se um arquivo serve (a tela inicial, o processo que repassa os arquivos do botão direito para o
RDF já aberto) não carrega o PyMuPDF nem o Pillow: a abertura do app fica mais rápida. A conversão de cada formato
para PDF está em sources.py.
"""

from pathlib import Path

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp', '.gif'}
TEXT_EXTENSIONS = {'.txt', '.md', '.csv', '.log', '.json', '.xml'}
HTML_EXTENSIONS = {'.html', '.htm'}
MUPDF_EXTENSIONS = {'.svg', '.cbz'}
WORD_EXTENSIONS = {'.doc', '.docx', '.rtf', '.odt'}
EXCEL_EXTENSIONS = {'.xls', '.xlsx'}
POWERPOINT_EXTENSIONS = {'.ppt', '.pptx'}
OFFICE_EXTENSIONS = WORD_EXTENSIONS | EXCEL_EXTENSIONS | POWERPOINT_EXTENSIONS
ALL_EXTENSIONS = {'.pdf'} | IMAGE_EXTENSIONS | TEXT_EXTENSIONS | HTML_EXTENSIONS | MUPDF_EXTENSIONS | OFFICE_EXTENSIONS


def extension(path):
    return Path(path).suffix.lower()


def is_supported(path):
    return extension(path) in ALL_EXTENSIONS

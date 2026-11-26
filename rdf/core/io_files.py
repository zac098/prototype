"""Validação do conteúdo real dos arquivos de entrada."""

from pathlib import Path

import fitz
from PIL import Image

INPUT_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp'}
IMAGE_FORMAT_BY_EXTENSION = {
    '.png': 'PNG',
    '.jpg': 'JPEG',
    '.jpeg': 'JPEG',
    '.bmp': 'BMP',
    '.tif': 'TIFF',
    '.tiff': 'TIFF',
    '.webp': 'WEBP',
}


def validate_input_content(path):
    """Validate the real file content instead of trusting its extension."""
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    try:
        with file_path.open('rb') as stream:
            header = stream.read(1024)
    except OSError as exc:
        raise ValueError(f'Não foi possível ler o arquivo: {exc}') from exc
    if suffix == '.pdf':
        if not header.lstrip().startswith(b'%PDF-'):
            if len(header) >= 12 and header[4:8] == b'ftyp':
                raise ValueError('O arquivo tem extensão PDF, mas o conteúdo real é um vídeo MP4.')
            raise ValueError('O arquivo tem extensão PDF, mas o conteúdo não é um PDF válido.')
        try:
            with fitz.open(file_path) as document:
                if len(document) < 1:
                    raise ValueError('O PDF não possui páginas.')
        except Exception as exc:
            raise ValueError(f'O conteúdo PDF está inválido ou corrompido: {exc}') from exc
        return 'PDF'
    expected = IMAGE_FORMAT_BY_EXTENSION.get(suffix)
    if expected:
        try:
            with Image.open(file_path) as image:
                actual = (image.format or '').upper()
                image.verify()
        except Exception as exc:
            raise ValueError(f'O arquivo tem extensão {suffix.upper()}, mas não é uma imagem válida: {exc}') from exc
        # Accept a valid decodable image even when a scanner or messaging
        # application saved it under another supported image extension.
        return actual
    raise ValueError(f'Formato não suportado: {suffix or "sem extensão"}.')

import tempfile
import unittest
from pathlib import Path
import fitz
from PIL import Image

import _source  # coloca a raiz do projeto no sys.path
from rdf.core.io_files import validate_input_content


class ContentValidationTests(unittest.TestCase):
    def test_rejects_mp4_renamed_as_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'video.pdf'
            path.write_bytes(b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp41isom')
            with self.assertRaisesRegex(ValueError, 'vídeo MP4'):
                validate_input_content(path)

    def test_rejects_arbitrary_content_renamed_as_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'falso.pdf'
            path.write_bytes(b'isto nao e um pdf')
            with self.assertRaisesRegex(ValueError, 'não é um PDF válido'):
                validate_input_content(path)

    def test_accepts_real_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'real.pdf'
            document = fitz.open()
            document.new_page()
            document.save(path)
            document.close()
            self.assertEqual(validate_input_content(path), 'PDF')

    def test_accepts_png_with_png_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'imagem.png'
            Image.new('RGB', (2, 2), 'white').save(path, 'PNG')
            self.assertEqual(validate_input_content(path), 'PNG')

    def test_accepts_valid_png_content_named_jpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'imagem.jpeg'
            Image.new('RGB', (2, 2), 'white').save(path, 'PNG')
            self.assertEqual(validate_input_content(path), 'PNG')

    def test_rejects_non_image_named_jpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'falso.jpeg'
            path.write_bytes(b'not an image')
            with self.assertRaisesRegex(ValueError, 'não é uma imagem válida'):
                validate_input_content(path)

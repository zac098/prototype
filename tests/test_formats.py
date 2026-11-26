import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image

import _source  # coloca a raiz do projeto no sys.path
from rdf.core.config import OUTPUT_FORMATS
from rdf.core.io_files import IMAGE_FORMAT_BY_EXTENSION, INPUT_EXTENSIONS


class FormatTests(unittest.TestCase):
    def test_supported_inputs(self):
        self.assertEqual(INPUT_EXTENSIONS, {'.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp'})
        self.assertEqual(set(IMAGE_FORMAT_BY_EXTENSION), INPUT_EXTENSIONS - {'.pdf'})

    def test_supported_outputs(self):
        self.assertEqual(OUTPUT_FORMATS, ('PDF', 'PNG', 'JPEG', 'JPG', 'WEBP', 'BMP', 'TIFF'))

    def test_image_pdf_roundtrip_primitives(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'a.pdf'
            Image.new('RGB', (40, 30), 'white').save(path, 'PDF')
            with fitz.open(path) as document:
                self.assertEqual(len(document), 1)


if __name__ == '__main__':
    unittest.main()

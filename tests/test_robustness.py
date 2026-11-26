"""Trava do PyMuPDF, timeout do Tesseract, limites das ferramentas e fechamento só do Office do próprio RDF."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _source  # coloca a raiz do projeto no sys.path
import fitz
from rdf.core import imaging, ocr
from rdf.core.fitz_lock import FITZ_LOCK
from rdf.pdftools import ops, sources


def make_pdf(path, pages=2):
    document = fitz.open()
    for number in range(pages):
        document.new_page().insert_text((72, 72), f'pagina {number + 1}')
    document.save(path)
    document.close()
    return str(path)


class FitzLockTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pdf = make_pdf(Path(tmp.name) / 'a.pdf')

    def assert_opened_under_lock(self, call):
        held = []
        real_open = fitz.open

        def spy(*args, **kwargs):
            held.append(FITZ_LOCK._is_owned())
            return real_open(*args, **kwargs)

        with mock.patch.object(imaging.fitz, 'open', spy), mock.patch.object(ocr.fitz, 'open', spy):
            call()
        self.assertTrue(held)
        self.assertTrue(all(held), 'o PyMuPDF foi aberto sem a trava')

    def test_rendering_functions_hold_the_lock(self):
        self.assert_opened_under_lock(lambda: imaging.render_pdf_page(self.pdf))
        self.assert_opened_under_lock(lambda: imaging.render_header_candidates(self.pdf))
        self.assert_opened_under_lock(lambda: imaging.render_full_page(self.pdf))

    def test_ocr_text_readers_hold_the_lock(self):
        self.assert_opened_under_lock(lambda: ocr._embedded_document_text(self.pdf))
        self.assert_opened_under_lock(lambda: ocr._page_data(self.pdf, 0, 1.0))
        with mock.patch.object(ocr, '_image_to_string', return_value=''):
            self.assert_opened_under_lock(lambda: ocr._document_search_text(self.pdf))
            self.assert_opened_under_lock(lambda: ocr._document_search_text_exhaustive(self.pdf))

    def test_page_data_returns_total_text_and_image(self):
        total, text, image = ocr._page_data(self.pdf, 1, 1.0)
        self.assertEqual(total, 2)
        self.assertIn('pagina 2', text)
        self.assertEqual(image.ndim, 3)
        self.assertEqual(ocr._page_data(self.pdf, 9), (2, '', None))


class TesseractTimeoutTests(unittest.TestCase):
    def test_every_read_passes_a_timeout(self):
        with mock.patch.object(ocr.pytesseract, 'image_to_string', return_value='x') as read:
            ocr._image_to_string(object(), '--psm 6')
        self.assertEqual(read.call_args.kwargs['timeout'], ocr.OCR_TIMEOUT_SECONDS)
        with mock.patch.object(ocr.pytesseract, 'image_to_data', return_value={}) as read:
            ocr._image_to_data(object(), '--psm 6')
        self.assertEqual(read.call_args.kwargs['timeout'], ocr.OCR_TIMEOUT_SECONDS)

    def test_a_timeout_becomes_a_clear_message(self):
        with mock.patch.object(
            ocr.pytesseract, 'image_to_string', side_effect=RuntimeError('Tesseract process timeout')
        ):
            with self.assertRaises(RuntimeError) as caught:
                ocr._image_to_string(object(), '--psm 6')
        self.assertIn('demorou mais de', str(caught.exception))

    def test_other_runtime_errors_pass_through(self):
        with mock.patch.object(ocr.pytesseract, 'image_to_string', side_effect=RuntimeError('outro erro')):
            with self.assertRaisesRegex(RuntimeError, 'outro erro'):
                ocr._image_to_string(object(), '--psm 6')

    def test_the_ocr_tool_reports_a_timeout_as_a_tool_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = make_pdf(Path(tmp) / 'a.pdf', pages=1)
            with mock.patch(
                'pytesseract.image_to_pdf_or_hocr', side_effect=RuntimeError('Tesseract process timeout')
            ) as read:
                with self.assertRaises(ops.PdfToolError) as caught:
                    ops.ocr_pdf(pdf, str(Path(tmp) / 'out.pdf'))
            self.assertEqual(read.call_args.kwargs['timeout'], ops.OCR_PAGE_TIMEOUT)
            self.assertIn('página 1', str(caught.exception))


class SizeLimitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_text_and_html_have_a_lower_limit_than_pdf(self):
        self.assertLess(sources.TEXT_MAX_MB, sources.TOOL_MAX_MB)

    def test_a_big_text_file_is_refused_with_a_clear_message(self):
        big = self.tmp / 'log.txt'
        big.write_bytes(b'x' * (2 * 1024 * 1024))
        with mock.patch.object(sources, 'TEXT_MAX_MB', 1):
            message = sources.size_error(big)
            with self.assertRaises(ops.PdfToolError):
                sources.convert_to_pdf(big, self.tmp / 'out.pdf')
        self.assertIn('log.txt', message)
        self.assertIn('limite', message)

    def test_files_inside_the_limit_and_missing_files_are_accepted(self):
        small = self.tmp / 'a.txt'
        small.write_text('ok', encoding='utf-8')
        self.assertIsNone(sources.size_error(small))
        self.assertIsNone(sources.size_error(self.tmp / 'nao-existe.pdf'))

    def test_a_pdf_uses_the_tool_limit(self):
        pdf = Path(make_pdf(self.tmp / 'a.pdf'))
        with mock.patch.object(sources, 'TOOL_MAX_MB', 0):
            self.assertIn('a.pdf', sources.size_error(pdf))

    def test_an_image_with_too_many_pixels_is_refused(self):
        from PIL import Image

        path = self.tmp / 'foto.png'
        Image.new('RGB', (40, 30)).save(path)
        with mock.patch.object(sources, 'MAX_IMAGE_PIXELS', 1000):
            with self.assertRaises(ops.PdfToolError) as caught:
                sources.convert_to_pdf(path, self.tmp / 'out.pdf')
        self.assertIn('pixels', str(caught.exception))
        self.assertIsNone(sources.pixels_error(40, 30, 'foto.png'))


class OfficeOwnershipTests(unittest.TestCase):
    def test_every_script_records_its_own_processes_right_after_starting_the_app(self):
        for app, (name, process) in {'Word': ('Word', 'WINWORD'), 'Excel': ('Excel', 'EXCEL')}.items():
            body = sources._POWERSHELL_SCRIPTS[app].replace('@OWN@', sources._POWERSHELL_OWN)
            script = sources._POWERSHELL_PRELUDE + body + sources._POWERSHELL_CLEANUP
            script = script.replace('{process}', process)
            start = script.index(f'New-Object -ComObject {name}.Application')
            self.assertLess(start, script.index('$meus = @(Get-Process'))
            self.assertIn('$meus -contains $_.Id', script)
            self.assertNotIn('@OWN@', script)


if __name__ == '__main__':
    unittest.main()

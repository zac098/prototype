"""Correções da revisão de código da 4.0: cada teste reproduz o problema encontrado e trava a correção."""

import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import _source  # coloca a raiz do projeto no sys.path
import fitz
import numpy as np
from PIL import Image
from rdf.core import batch, config, exporter, inputs, io_files, ocr
from rdf.core.fitz_lock import FITZ_LOCK
from rdf.pdftools import ops

HAS_QT = importlib.util.find_spec('PySide6') is not None
MM = 72 / 25.4


def make_pdf(path, pages=1, size=(595, 842)):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for number in range(pages):
        document.new_page(width=size[0], height=size[1]).insert_text((72, 72), f'pagina {number + 1}')
    document.save(path)
    document.close()
    return str(path)


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)


class NamingOptionsTests(unittest.TestCase):
    """Trocar as opções de nome (ou o formato) não pode tornar exportável quem não foi reconhecido."""

    def setUp(self):
        self.lote = batch.Batch()
        self.lote.files = ['a.pdf', 'b.pdf', 'c.pdf', 'd.pdf']
        self.lote.rows = {
            'a.pdf': {'path': 'a.pdf', 'status': 'NAO RECONHECIDO', 'method': 'OCR', 'new': '', 'conf': 0},
            'b.pdf': {'path': 'b.pdf', 'status': 'Pendente', 'method': '', 'new': '', 'conf': 0},
            'c.pdf': {
                'path': 'c.pdf',
                'status': 'OK',
                'method': 'OCR',
                'chapa': '1',
                'nome': 'ANA SOUZA',
                'mes': None,
                'conf': 0.95,
                'chapa_source': 'documento',
                'new': '',
            },
            'd.pdf': {
                'path': 'd.pdf',
                'status': 'CORRIGIDO',
                'method': 'Manual',
                'chapa': '2',
                'nome': 'BIA LIMA',
                'mes': 'MARÇO',
                'conf': 1.0,
                'new': '',
            },
        }

    def test_unrecognized_and_pending_rows_stay_as_they_were(self):
        self.lote.set_options(True, True, False)  # desmarca o mês
        self.lote.refresh_names()
        self.assertEqual(self.lote.rows['a.pdf']['status'], 'NAO RECONHECIDO')
        self.assertEqual(self.lote.rows['a.pdf']['new'], '')
        self.assertEqual(self.lote.rows['b.pdf']['status'], 'Pendente')
        self.assertEqual(exporter.exportable_items(self.lote), [('c.pdf', '1 - ANA SOUZA'), ('d.pdf', '2 - BIA LIMA')])

    def test_read_rows_follow_the_options_and_settled_ones_keep_their_status(self):
        self.lote.refresh_names()  # com o mês marcado, a folha sem mês vai para revisão
        self.assertEqual(self.lote.rows['c.pdf']['status'], 'REVISAR')
        self.assertEqual(self.lote.rows['d.pdf']['status'], 'CORRIGIDO')
        self.assertEqual(self.lote.rows['d.pdf']['new'], '2 - BIA LIMA - MARÇO.PDF')

    def test_correcting_a_certificate_turns_it_into_a_timesheet(self):
        self.lote.rows['a.pdf'].update({'category': 'Atestados', 'document_type': 'Atestado', 'status': 'OK'})
        row = self.lote.correct('a.pdf', {'chapa': '123', 'nome': 'JOAO PEREIRA', 'mes': 'MAIO'})
        self.assertIsNone(row['category'])
        self.assertEqual(row['document_type'], 'Folha de ponto')
        self.assertEqual(self.lote.confidence_text(row), '100%')


class CropAgainTests(TempCase):
    def test_cropping_an_already_cropped_pdf_removes_more(self):
        first, second = self.tmp / 'c1.pdf', self.tmp / 'c2.pdf'
        ops.crop_pdf(make_pdf(self.tmp / 'c0.pdf'), first, top=20, left=20, bottom=0, right=0)
        ops.crop_pdf(first, second, top=5, left=0, bottom=0, right=0)
        with fitz.open(second) as document:
            box = [round(value / MM, 1) for value in document[0].cropbox]
        self.assertEqual(box[:2], [20.0, 25.0])  # 20 mm de antes + 5 mm agora, a partir da página inteira


class BestReadingTests(unittest.TestCase):
    def test_a_good_reading_wins_over_a_weak_one_that_only_has_the_month(self):
        good = (('123456', 'MARIA SOUZA LIMA', None, 'documento'), 0.90, 0)
        weak = (('123456', 'MARIA S', 'março', 'documento'), 0.55, 0)
        self.assertIs(ocr._best_attempt([weak, good]), good)

    def test_without_complete_readings_the_month_and_then_confidence_decide(self):
        a = (('1', 'ANA SOUZA', None, 'documento'), 0.60, 0)
        b = (('1', 'ANA SOUZ', 'maio', 'documento'), 0.50, 0)
        self.assertIs(ocr._best_attempt([a, b]), b)

    def test_the_month_of_the_weak_reading_completes_the_good_one(self):
        replies = [
            'Chapa/Nome 123456 MARIA SOUZA LIMA Admissão 01/01/2020',
            'MARÇO/2026 Chapa/Nome 123456 MARIA S Admissão',
        ]
        data = [ocr_data(text, confidence) for text, confidence in zip(replies, (90, 55))]
        path = make_pdf(Path(tempfile.mkdtemp()) / 'f.pdf')
        with (
            mock.patch.object(ocr, '_image_to_data', side_effect=data + [ocr_data('')] * 20),
            mock.patch.object(ocr, '_document_search_text', return_value=''),
        ):
            parsed, _method, conf = ocr.analyze_pdf(path, 0, {'header': [], 'fast_page': None})
        self.assertEqual(parsed[:3], ('123456', 'MARIA SOUZA LIMA', 'março'))
        self.assertAlmostEqual(conf, 0.90)


def ocr_data(text, confidence=90):
    tokens = text.split()
    size = len(tokens)
    return {
        'text': tokens,
        'conf': [str(confidence)] * size,
        'block_num': [1] * size,
        'par_num': [1] * size,
        'line_num': [1] * size,
    }


class LockTests(TempCase):
    """Quem abre o PyMuPDF na thread da janela também usa a trava (a prévia e as miniaturas rodam ao lado)."""

    def assert_opened_under_lock(self, module, call):
        held = []
        real_open = fitz.open

        def spy(*args, **kwargs):
            held.append(FITZ_LOCK._is_owned())
            return real_open(*args, **kwargs)

        with mock.patch.object(module.fitz, 'open', spy):
            call()
        self.assertTrue(held)
        self.assertTrue(all(held), 'o PyMuPDF foi aberto sem a trava')

    def test_input_helpers_hold_the_lock(self):
        pdf = make_pdf(self.tmp / 'a.pdf', 2)
        with mock.patch.object(config, 'SPLIT_DIR', self.tmp / 'paginas'):
            (self.tmp / 'paginas').mkdir()
            self.assert_opened_under_lock(inputs, lambda: inputs.split_pdf_pages(pdf))
        self.assert_opened_under_lock(inputs, lambda: inputs.pdf_page_total(pdf))
        inputs._PAGE_COUNTS.clear()
        self.assert_opened_under_lock(inputs, lambda: inputs.input_page_count(pdf))
        self.assert_opened_under_lock(io_files, lambda: io_files.validate_input_content(pdf))

    def test_export_holds_the_lock(self):
        pdf = make_pdf(self.tmp / 'a.pdf', 2)
        self.assert_opened_under_lock(exporter, lambda: exporter.planned_export_paths(pdf, self.tmp / 'x.png', 'PNG'))
        self.assert_opened_under_lock(exporter, lambda: exporter.export_source(pdf, self.tmp / 'y.png', 'PNG'))


class MultiFrameImageTests(TempCase):
    def test_every_frame_of_a_tiff_counts_toward_the_page_limit(self):
        frames = [Image.new('L', (40, 40), color) for color in (0, 80, 160)]
        path = self.tmp / 'scanner.tif'
        frames[0].save(path, save_all=True, append_images=frames[1:])
        inputs._PAGE_COUNTS.clear()
        self.assertEqual(inputs.input_page_count(path), 3)
        self.assertEqual(inputs.input_page_count(self.tmp / 'scanner.tif'), 3)  # do cache


class NoOverwriteTests(TempCase):
    def test_image_export_never_replaces_a_file_that_appeared_meanwhile(self):
        pdf = make_pdf(self.tmp / 'a.pdf')
        target = self.tmp / 'A.PNG'
        target.write_bytes(b'do usuario')
        with self.assertRaises(FileExistsError):
            exporter.export_source(pdf, self.tmp / 'a.png', 'PNG')
        self.assertEqual(target.read_bytes(), b'do usuario')


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class PrintMarginTests(TempCase):
    def test_the_page_is_centered_inside_the_margins_not_pushed_out(self):
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QPageLayout
        from PySide6.QtPrintSupport import QPrinter
        from rdf.pdftools import printing
        from rdf.qt.__main__ import create_app

        create_app([])
        source = self.tmp / 'preta.pdf'
        document = fitz.open()
        page = document.new_page(width=595, height=842)
        page.draw_rect(page.rect, color=(0, 0, 0), fill=(0, 0, 0))
        document.save(source)
        document.close()
        output = self.tmp / 'impresso.pdf'
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(output))
        printer.setPageMargins(QMarginsF(20, 20, 20, 20), QPageLayout.Millimeter)
        printing.print_document(source, printer)
        with fitz.open(output) as printed:
            pix = printed[0].get_pixmap(dpi=36)
        pixels = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, 0]
        ys, xs = np.where(pixels < 128)
        to_mm = 25.4 / 36
        left, right = xs.min() * to_mm, (pix.width - 1 - xs.max()) * to_mm
        self.assertAlmostEqual(left, 20, delta=2.5)  # antes: 40 mm (margem contada duas vezes)
        self.assertAlmostEqual(right, 20, delta=2.5)  # antes: 0 mm (a direita saía cortada)


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class RetiredRenamerTests(TempCase):
    def test_a_renamer_still_finishing_does_not_stop_the_app_from_closing(self):
        from rdf.core import settings
        from rdf.qt.__main__ import create_app
        from rdf.qt.window import MainWindow

        app = create_app([])
        settings.reset()
        data = self.tmp / 'dados'
        for name, folder in (('SESSION_FILE', data / 's.json'), ('SPLIT_DIR', data / 'p'), ('CONVERT_DIR', data / 'c')):
            patch = mock.patch.object(config, name, folder)
            patch.start()
            self.addCleanup(patch.stop)
        (data / 'p').mkdir(parents=True)
        window = MainWindow()
        self.addCleanup(window.deleteLater)
        page = window.open_tool('renamer')
        temp = data / 'p' / 'copia.pdf'
        temp.write_bytes(b'%PDF-1.4')
        page.batch.generated_files.add(str(temp))
        page.analysis_running = True  # uma análise cancelada ainda terminando
        with (
            mock.patch.object(window, 'ask_cancel_to_leave', return_value=True),
            mock.patch.object(window, 'stop_and_wait'),
        ):
            self.assertTrue(window.request_home())
        self.assertIn(page, window._retired)
        self.assertTrue(temp.exists())  # ainda em uso pela análise
        deadline = time.monotonic() + 1

        def finish():  # a análise termina logo depois que a janela pede para fechar
            page.analysis_running = False
            page.finish_analysis()

        with (
            mock.patch('rdf.qt.window.CANCEL_WAIT_SECONDS', 1),
            mock.patch.object(page, 'cancel_for_exit', side_effect=finish),
        ):
            self.assertTrue(window.close())
        self.assertLess(time.monotonic(), deadline + 2)
        self.assertFalse(temp.exists())  # a cópia com dados pessoais foi apagada ao terminar
        app.processEvents()


if __name__ == '__main__':
    unittest.main()

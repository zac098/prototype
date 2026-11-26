"""Testes de comportamento do OCR e da imagem, com o Tesseract simulado."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import fitz
import numpy as np

import _source  # coloca a raiz do projeto no sys.path
from rdf.core import imaging, ocr

A4_WIDTH, A4_HEIGHT = 595, 842


def make_pdf(path, pages=1, text=None):
    document = fitz.open()
    for _ in range(pages):
        page = document.new_page(width=A4_WIDTH, height=A4_HEIGHT)
        if text:
            page.insert_text((72, 72), text)
    document.save(path)
    document.close()
    return str(path)


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


class FakeTesseract:
    """Registra cada chamada e devolve as respostas na ordem dada."""

    def __init__(self, replies=()):
        self.replies = list(replies)
        self.calls = []

    def image_to_string(self, image, lang=None, config=None, timeout=None):
        self.calls.append((image.shape[:2], config))
        return self.replies.pop(0) if self.replies else ''

    def image_to_data(self, image, lang=None, config=None, output_type=None, timeout=None):
        self.calls.append((image.shape[:2], config))
        return self.replies.pop(0) if self.replies else ocr_data('')

    def patch(self, name):
        return mock.patch.object(ocr.pytesseract, name, side_effect=getattr(self, name))


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class FastDocumentSearchTests(TempDirTestCase):
    def test_blank_page_tries_upright_then_sideways_once(self):
        pdf = make_pdf(self.tmp / 'branco.pdf')
        fake = FakeTesseract()
        with fake.patch('image_to_string'):
            ocr._document_search_text(pdf)
        shapes = [shape for shape, _ in fake.calls]
        self.assertEqual(len(shapes), 4)  # 0 e 180 graus, depois 90 e 270 graus
        upright = shapes[0]
        self.assertEqual(shapes[1], upright)
        self.assertEqual(shapes[2], upright[::-1])
        self.assertEqual(shapes[3], upright[::-1])
        self.assertAlmostEqual(upright[1], A4_WIDTH * 1.8, delta=2)  # renderização em 1,8x

    def test_stops_as_soon_as_evidence_is_enough(self):
        pdf = make_pdf(self.tmp / 'atestado.pdf')
        fake = FakeTesseract(['ATESTADO MEDICO'])
        with fake.patch('image_to_string'):
            text = ocr._document_search_text(pdf)
        self.assertEqual(len(fake.calls), 1)
        self.assertIn('ATESTADO', text)

    def test_strong_embedded_text_skips_tesseract(self):
        pdf = make_pdf(self.tmp / 'declaracao.pdf', text='DECLARACAO DE COMPARECIMENTO')
        fake = FakeTesseract()
        with fake.patch('image_to_string'):
            ocr._document_search_text(pdf)
        self.assertEqual(fake.calls, [])

    def test_weak_embedded_text_still_tries_sideways(self):
        pdf = make_pdf(self.tmp / 'fraco.pdf', text='relatorio mensal')
        fake = FakeTesseract()
        with fake.patch('image_to_string'):
            ocr._document_search_text(pdf)
        self.assertEqual(len(fake.calls), 4)


class ExhaustiveDocumentSearchTests(TempDirTestCase):
    def test_blank_page_runs_full_legacy_matrix(self):
        pdf = make_pdf(self.tmp / 'branco.pdf')
        fake = FakeTesseract()
        with fake.patch('image_to_string'):
            ocr._document_search_text_exhaustive(pdf)
        self.assertEqual(len(fake.calls), 12)  # 4 ângulos x 3 combinações
        configs = [config for _, config in fake.calls[:3]]
        self.assertEqual(configs, ['--oem 3 --psm 6', '--oem 3 --psm 11', '--oem 3 --psm 11'])
        self.assertAlmostEqual(fake.calls[0][0][1], A4_WIDTH * 2.4, delta=2)  # renderização em 2,4x


class AnalyzeDocumentRoutingTests(unittest.TestCase):
    """Ordem dos caminhos: texto embutido, cabeçalho, OCR rápido e, por último, o completo."""

    def run_routing(self, embedded='', parsed=None, header='', fast_page=None, fast='', exhaustive=''):
        calls = []

        def fake_analyze_pdf(path, page_index, context):
            calls.append('analyze_pdf')
            context['header'].append(header)
            context['fast_page'] = fast_page
            return (parsed, 'OCR', 0.9) if parsed else (None, 'Falhou', 0)

        def recorder(name, value):
            def fake(*args, **kwargs):
                calls.append(name)
                return value

            return fake

        with (
            mock.patch.object(ocr, '_embedded_document_text', recorder('embedded', embedded)),
            mock.patch.object(ocr, 'analyze_pdf', fake_analyze_pdf),
            mock.patch.object(ocr, '_document_search_text', recorder('fast', fast)),
            mock.patch.object(ocr, '_document_search_text_exhaustive', recorder('exhaustive', exhaustive)),
        ):
            result = ocr.analyze_document('qualquer.pdf')
        return result, calls

    def test_embedded_document_text_skips_ocr(self):
        result, calls = self.run_routing(embedded='DECLARACAO DE COMPARECIMENTO')
        self.assertEqual(calls, ['embedded'])
        self.assertEqual(result['category'], 'Declarações')

    def test_timesheet_stops_before_document_ocr(self):
        parsed = ('125530', 'ANGELA DA COSTA', 'setembro', 'documento')
        result, calls = self.run_routing(parsed=parsed)
        self.assertEqual(calls, ['embedded', 'analyze_pdf'])
        self.assertEqual(result['document_type'], 'Folha de ponto')

    def test_header_ocr_is_reused_for_classification(self):
        result, calls = self.run_routing(header='ATESTADO MEDICO')
        self.assertEqual(calls, ['embedded', 'analyze_pdf'])
        self.assertEqual(result['category'], 'Atestados')

    def test_fast_page_from_header_step_is_reused(self):
        _, calls = self.run_routing(fast_page='')
        self.assertEqual(calls, ['embedded', 'analyze_pdf', 'exhaustive'])

    def test_exhaustive_runs_only_after_fast_paths_fail(self):
        result, calls = self.run_routing()
        self.assertEqual(calls, ['embedded', 'analyze_pdf', 'fast', 'exhaustive'])
        self.assertEqual(result['document_type'], 'Não identificado')

    def test_fast_success_skips_exhaustive(self):
        result, calls = self.run_routing(fast='DECLARACAO DE COMPARECIMENTO')
        self.assertEqual(calls, ['embedded', 'analyze_pdf', 'fast'])
        self.assertEqual(result['category'], 'Declarações')


class AnalyzePdfTests(TempDirTestCase):
    def test_embedded_header_is_read_without_tesseract(self):
        pdf = make_pdf(self.tmp / 'folha.pdf', text='Chapa/Nome: 125530 - ANGELA DA COSTA SILVA Funcao: X')
        fake = FakeTesseract()
        with fake.patch('image_to_data'):
            parsed, method, confidence = ocr.analyze_pdf(pdf)
        self.assertEqual(parsed[:2], ('125530', 'ANGELA DA COSTA SILVA'))
        self.assertEqual((method, confidence), ('Texto', 0.99))
        self.assertEqual(fake.calls, [])

    def test_filename_never_supplies_the_registration(self):
        pdf = make_pdf(self.tmp / '125530.pdf')
        fake = FakeTesseract()
        with fake.patch('image_to_data'):
            self.assertEqual(ocr.analyze_pdf(pdf), (None, 'Falhou', 0))

    def test_confident_otsu_read_skips_expensive_preprocessing(self):
        pdf = make_pdf(self.tmp / 'folha.pdf')
        header = 'FOLHA DE PONTO SETEMBRO/2026 Chapa/Nome: 125530 - ANGELA DA COSTA SILVA Funcao: X'
        fake = FakeTesseract([ocr_data(header)])
        with (
            fake.patch('image_to_data'),
            mock.patch.object(ocr, 'preprocess', side_effect=AssertionError('preprocess não deveria rodar')),
        ):
            parsed, method, confidence = ocr.analyze_pdf(pdf, 0, {'header': [], 'fast_page': None})
        self.assertEqual(parsed[:3], ('125530', 'ANGELA DA COSTA SILVA', 'setembro'))
        self.assertEqual(method, 'OCR')
        self.assertAlmostEqual(confidence, 0.9)
        self.assertEqual(len(fake.calls), 1)

    def test_page_outside_document_is_rejected(self):
        pdf = make_pdf(self.tmp / 'uma.pdf')
        with self.assertRaises(IndexError), self.assertLogs('rdf', 'ERROR'):
            ocr.analyze_pdf(pdf, page_index=3)


class RenderTests(TempDirTestCase):
    def test_header_candidates_use_chosen_page_top_and_rotated_bottom(self):
        pdf = make_pdf(self.tmp / 'duas.pdf', pages=2)
        candidates = imaging.render_header_candidates(pdf, page_index=1)
        self.assertEqual([angle for angle, _ in candidates], [0, 180])
        for _, image in candidates:
            self.assertAlmostEqual(image.shape[0], A4_HEIGHT * 0.34 * 3, delta=3)
            self.assertAlmostEqual(image.shape[1], A4_WIDTH * 3, delta=3)
        with self.assertRaises(IndexError):
            imaging.render_header_candidates(pdf, page_index=2)

    def test_page_render_clamps_index_and_reports_total(self):
        pdf = make_pdf(self.tmp / 'duas.pdf', pages=2)
        image, total = imaging.render_pdf_page(pdf, page_index=9)
        self.assertEqual(total, 2)
        self.assertEqual(image.ndim, 3)


class PhotoPerspectiveTests(unittest.TestCase):
    def test_photographed_sheet_is_cropped_and_straightened(self):
        photo = np.full((1200, 1000, 3), 40, np.uint8)
        corners = np.array([[150, 80], [850, 120], [880, 1100], [120, 1080]], np.int32)
        cv2.fillPoly(photo, [corners], (245, 245, 245))
        corrected, changed = imaging.rectify_document_photo(photo)
        self.assertTrue(changed)
        height, width = corrected.shape[:2]
        self.assertGreater(height, width)
        self.assertLess(height, 1200)
        self.assertGreater(corrected.mean(), 200)  # a margem escura foi removida

    def test_small_or_featureless_images_are_left_alone(self):
        small = np.zeros((400, 400, 3), np.uint8)
        self.assertIs(imaging.rectify_document_photo(small)[0], small)
        blank = np.full((1200, 1000, 3), 255, np.uint8)
        self.assertEqual(imaging.rectify_document_photo(blank), (blank, False))

    def test_landscape_shapes_are_not_treated_as_pages(self):
        photo = np.full((1000, 1400, 3), 40, np.uint8)
        cv2.rectangle(photo, (100, 200), (1300, 800), (245, 245, 245), -1)  # proporção 2:1
        self.assertFalse(imaging.rectify_document_photo(photo)[1])


if __name__ == '__main__':
    unittest.main()

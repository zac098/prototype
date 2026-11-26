"""Fotos e imagens (JPG, PNG...) como entrada do renomeador: orientação, transparência, tamanho da página,
folha de scanner e leitura do cabeçalho em fotos difíceis."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import fitz
import numpy as np
from PIL import Image

import _source  # coloca a raiz do projeto no sys.path
from rdf.core import config, imaging, inputs, ocr
from rdf.core.parsing import parse_chapa_nome
from test_ocr_behavior import FakeTesseract, make_pdf, ocr_data


class ImageConversionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        patch = mock.patch.object(config, 'CONVERT_DIR', self.tmp / 'convertidos')
        patch.start()
        self.addCleanup(patch.stop)
        (self.tmp / 'convertidos').mkdir()

    def page_array(self, pdf):
        image, _total = imaging.render_pdf_page(pdf, 0, scale=1.0)
        return image

    def test_the_exif_rotation_is_applied(self):
        """O scanner e o celular gravam "gire 180°" no EXIF: sem aplicar, a folha chega de cabeça para baixo."""
        picture = Image.new('RGB', (400, 600), 'white')
        picture.paste((0, 0, 0), (0, 0, 400, 150))  # faixa preta no topo
        exif = Image.Exif()
        exif[274] = 3  # 180 graus
        path = self.tmp / 'scanner.jpg'
        picture.save(path, 'JPEG', exif=exif)
        array = self.page_array(inputs.image_to_pdf(path))
        quarter = array.shape[0] // 4
        self.assertGreater(array[:quarter].mean(), 200)  # o topo agora é branco
        self.assertLess(array[-quarter:].mean(), 60)  # e a faixa preta foi para baixo

    def test_an_image_without_exif_keeps_its_orientation(self):
        picture = Image.new('RGB', (400, 600), 'white')
        picture.paste((0, 0, 0), (0, 0, 400, 150))
        path = self.tmp / 'normal.png'
        picture.save(path)
        array = self.page_array(inputs.image_to_pdf(path))
        self.assertLess(array[: array.shape[0] // 4].mean(), 60)

    def test_a_transparent_png_gets_a_white_background(self):
        path = self.tmp / 'transparente.png'
        Image.new('RGBA', (300, 400), (0, 0, 0, 0)).save(path)  # transparente com preto por baixo
        array = self.page_array(inputs.image_to_pdf(path))
        self.assertGreater(array.mean(), 250)

    def test_a_half_transparent_png_blends_with_white(self):
        path = self.tmp / 'meio.png'
        Image.new('RGBA', (300, 400), (0, 0, 0, 128)).save(path)
        array = self.page_array(inputs.image_to_pdf(path))
        self.assertTrue(100 < array.mean() < 160)

    def test_palette_png_with_transparency_converts(self):
        path = self.tmp / 'paleta.png'
        picture = Image.new('P', (300, 400), 0)
        picture.info['transparency'] = 0
        picture.save(path, transparency=0)
        self.assertGreater(self.page_array(inputs.image_to_pdf(path)).mean(), 250)

    def test_page_size_follows_the_image_size_but_is_capped(self):
        def width_pt(pixels):
            path = self.tmp / f'img_{pixels}.png'
            Image.new('RGB', (pixels, pixels * 4 // 3), 'white').save(path)
            with fitz.open(inputs.image_to_pdf(path)) as document:
                return document[0].rect.width

        small, medium, big = width_pt(590), width_pt(1200), width_pt(2550)
        self.assertLess(small, medium)
        self.assertAlmostEqual(small, 590 * 72 / inputs.MIN_PAGE_DPI, delta=2)  # perto do tamanho real
        self.assertAlmostEqual(big, inputs.MAX_HEADER_WIDTH / 3, delta=2)  # uma folha A4 (595 pt) para o scanner

    def test_page_resolution_never_goes_below_the_minimum(self):
        self.assertEqual(inputs.page_resolution(10, 10), inputs.MIN_PAGE_DPI)
        self.assertGreater(inputs.page_resolution(5000, 7000), inputs.page_resolution(2550, 3300))


class ScannerSheetTests(unittest.TestCase):
    def test_a_scanned_sheet_is_not_cropped_to_its_table(self):
        """No scanner a folha ocupa a imagem toda; cortar na tabela jogaria fora o cabeçalho com a matrícula."""
        scan = np.full((1300, 1000, 3), 250, np.uint8)
        cv2.rectangle(scan, (60, 260), (940, 1240), (40, 40, 40), 6)  # a tabela, ~70% da folha
        for y in range(330, 1200, 70):
            cv2.line(scan, (60, y), (940, y), (60, 60, 60), 3)
        corrected, changed = imaging.rectify_document_photo(scan)
        self.assertFalse(changed)
        self.assertIs(corrected, scan)

    def test_a_dark_background_still_crops_the_sheet(self):
        photo = np.full((1200, 1000, 3), 40, np.uint8)
        corners = np.array([[150, 100], [850, 140], [820, 1100], [120, 1060]], np.int32)
        cv2.fillPoly(photo, [corners], (245, 245, 245))
        _corrected, changed = imaging.rectify_document_photo(photo)
        self.assertTrue(changed)


class GarbledLabelTests(unittest.TestCase):
    def test_labels_garbled_by_low_resolution_still_parse(self):
        for label in ('Chapa/Nome', 'Chupa/Nomo', 'Chapalioma', 'Chapalhoma', 'Chapa Nome'):
            with self.subTest(label=label):
                parsed = parse_chapa_nome(f'{label}: 140000 - TIAGO RODOLPHO CLERICI FILHO Função: 416 - APRENDIZ')
                self.assertEqual(parsed[:2], ('140000', 'TIAGO RODOLPHO CLERICI FILHO'))

    def test_a_garbled_admission_label_ends_the_name(self):
        parsed = parse_chapa_nome('Chapa/Nome: 133753 - AMANDA VITORIA DA SILVA CINTRA DATA DE ADMUSSDO: 10/08/2026')
        self.assertEqual(parsed[1], 'AMANDA VITORIA DA SILVA CINTRA')

    def test_ordinary_text_is_not_mistaken_for_the_label(self):
        for text in ('Chapa de aco 1234 - JOAO DA SILVA', 'chapa e uma coisa 1234 - XX', 'Nome: 1234 - JOAO DA SILVA'):
            with self.subTest(text=text):
                self.assertIsNone(parse_chapa_nome(text))


class HeaderRescueTests(unittest.TestCase):
    GOOD = 'Chapa/Nome: 1234 - JOAO DA SILVA Função: 4'

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pdf = make_pdf(Path(self._tmp.name) / 'foto.pdf')

    def analyze(self, replies):
        fake = FakeTesseract(replies)
        # O pré-processamento (remoção de ruído) é pesado e não muda o fluxo: aqui o que importa é a ordem das leituras.
        gray = mock.patch.object(ocr, 'preprocess', side_effect=lambda image: cv2.cvtColor(image, cv2.COLOR_RGB2GRAY))
        with fake.patch('image_to_data'), gray:
            return ocr.analyze_pdf(self.pdf), fake

    def test_a_well_read_header_never_reaches_the_rescue(self):
        (parsed, method, _conf), fake = self.analyze([ocr_data(self.GOOD + ' Folha de ponto Setembro/2026')] * 6)
        self.assertEqual(parsed[:2], ('1234', 'JOAO DA SILVA'))
        self.assertLessEqual(len(fake.calls), 6)

    def test_when_the_normal_reads_find_nothing_the_crop_rescue_is_tried(self):
        replies = [ocr_data('')] * 6 + [ocr_data(self.GOOD)]  # 6 leituras normais em branco, a 7ª é o resgate
        (parsed, method, _conf), fake = self.analyze(replies)
        self.assertEqual(parsed[:2], ('1234', 'JOAO DA SILVA'))
        self.assertEqual(len(fake.calls), 12)  # sem mês a leitura não é "completa": o resgate segue até o fim
        self.assertIn('--psm 11', fake.calls[6][1])

    def test_the_rescue_stops_as_soon_as_a_complete_read_appears(self):
        complete = ocr_data(self.GOOD + ' Folha de ponto Setembro/2026', confidence=95)
        replies = [ocr_data('')] * 6 + [complete]
        (parsed, _method, _conf), fake = self.analyze(replies)
        self.assertEqual(parsed[2], 'setembro')
        self.assertEqual(len(fake.calls), 7)  # as 6 leituras normais mais uma só do resgate

    def test_a_weak_normal_read_is_replaced_by_a_better_rescue_read(self):
        weak = ocr_data('Chapa/Nome: 40000 - MAGO RODOLPHO XX', confidence=40)
        replies = [weak] + [ocr_data('')] * 5 + [ocr_data(self.GOOD, confidence=95)]
        (parsed, _method, conf), _fake = self.analyze(replies)
        self.assertEqual(parsed[:2], ('1234', 'JOAO DA SILVA'))
        self.assertGreater(conf, 0.9)

    def test_when_the_crops_fail_the_whole_page_is_read_as_a_last_resort(self):
        replies = [ocr_data('')] * 12 + [ocr_data(self.GOOD)]  # 6 normais + 6 do resgate por recortes
        (parsed, _method, _conf), fake = self.analyze(replies)
        self.assertEqual(parsed[:2], ('1234', 'JOAO DA SILVA'))
        full_page_shape = fake.calls[12][0]
        self.assertEqual(full_page_shape[1], ocr.FULL_PAGE_WIDTH)  # a página inteira, não um recorte

    def test_a_page_that_cannot_be_read_at_all_still_fails_cleanly(self):
        (parsed, method, conf), _fake = self.analyze([])
        self.assertEqual((parsed, method, conf), (None, 'Falhou', 0))


if __name__ == '__main__':
    unittest.main()

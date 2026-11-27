"""Leitura do cabeçalho sem trabalho à toa: para na primeira leitura completa e não lê a página inteira de uma folha.

Nas 20 folhas reais de teste, isso levou a análise de 63 s para 16 s com os mesmos resultados (matrícula, nome e
mês iguais em todas). Aqui o Tesseract é simulado, então a suíte roda sem ele.
"""

import os
import unittest
from unittest import mock

import _source  # coloca a raiz do projeto no sys.path
from rdf.core import config, ocr
from test_ocr_behavior import FakeTesseract, TempDirTestCase, make_pdf, ocr_data

COMPLETE = 'Folha de ponto MARÇO/2026 Chapa/Nome 123456 MARIA FICTICIA SOUZA Admissão 01/01/2020'
NO_MONTH = 'Chapa/Nome 123456 MARIA FICTICIA SOUZA Admissão 01/01/2020'


class HeaderEarlyExitTests(TempDirTestCase):
    def analyze(self, replies):
        fake = FakeTesseract([ocr_data(text) for text in replies])
        path = make_pdf(self.tmp / 'folha.pdf')
        with (
            fake.patch('image_to_data'),
            fake.patch('image_to_string'),
            mock.patch.object(ocr, '_document_search_text', return_value='') as page_text,
        ):
            parsed, method, conf = ocr.analyze_pdf(path, 0, {'header': [], 'fast_page': None})
        return parsed, method, conf, fake.calls, page_text

    def test_a_complete_first_reading_stops_right_away(self):
        parsed, method, _conf, calls, page_text = self.analyze([COMPLETE])
        self.assertEqual(parsed[:3], ('123456', 'MARIA FICTICIA SOUZA', 'março'))
        self.assertEqual(method, 'OCR')
        self.assertEqual(len(calls), 1)
        page_text.assert_not_called()

    def test_a_variant_that_completes_the_reading_skips_the_rest(self):
        # 1ª leitura sem o mês; a 1ª variação traz o mês: nada mais é lido (nem o rodapé, nem a página inteira)
        parsed, _method, _conf, calls, page_text = self.analyze([NO_MONTH, COMPLETE])
        self.assertEqual(parsed[2], 'março')
        self.assertEqual(len(calls), 2)
        page_text.assert_not_called()

    def test_the_month_of_one_reading_completes_another(self):
        parsed, _method, _conf, calls, _page_text = self.analyze([NO_MONTH, 'MARÇO/2026 sem cabeçalho', COMPLETE])
        self.assertEqual(parsed[:3], ('123456', 'MARIA FICTICIA SOUZA', 'março'))
        self.assertLessEqual(len(calls), 3)

    def test_a_timesheet_header_already_read_skips_the_full_page_check(self):
        # topo lido sem o mês (incompleto); o rodapé não tem cabeçalho: não precisa ler a página inteira
        replies = [NO_MONTH, NO_MONTH, NO_MONTH, NO_MONTH, 'rodape qualquer']
        parsed, _method, _conf, _calls, page_text = self.analyze(replies)
        self.assertEqual(parsed[0], '123456')
        page_text.assert_not_called()

    def test_without_any_header_the_full_page_is_still_checked(self):
        _parsed, _method, _conf, _calls, page_text = self.analyze(['nada aqui'])
        page_text.assert_called()  # pode ser um atestado ou uma declaração


class TesseractThreadTests(unittest.TestCase):
    def test_each_tesseract_uses_one_thread_unless_the_user_chose(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('OMP_THREAD_LIMIT', None)
            config.configure_tesseract('/pasta/que/nao/existe')
            self.assertEqual(os.environ['OMP_THREAD_LIMIT'], '1')
        with mock.patch.dict(os.environ, {'OMP_THREAD_LIMIT': '4'}):
            config.configure_tesseract('/pasta/que/nao/existe')
            self.assertEqual(os.environ['OMP_THREAD_LIMIT'], '4')


if __name__ == '__main__':
    unittest.main()

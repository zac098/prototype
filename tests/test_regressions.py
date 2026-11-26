import unittest
import _source  # coloca a raiz do projeto no sys.path
from rdf.core import parsing

ns = vars(parsing)


class ParserTests(unittest.TestCase):
    def test_document_chapa_is_trusted(self):
        got = ns['parse_chapa_nome']('Chapa/Nome: 125530 - ANGELA DA COSTA FERNANDES SILVA Funcao: X', '125530.pdf')
        self.assertEqual(got[:2], ('125530', 'ANGELA DA COSTA FERNANDES SILVA'))
        self.assertEqual(got[3], 'documento')

    def test_ocr_variants_of_chapa_nome_are_recognized(self):
        for label in ('Chupa/Nomo:', 'Chiupa/Nomo:', 'Chupa Nome:'):
            with self.subTest(label=label):
                got = ns['parse_chapa_nome'](
                    f'{label} 119105 - FABRICIO GABRIEL DA SILVA LIMA Data de admissao: 07/04/2025'
                )
                self.assertEqual(got[:2], ('119105', 'FABRICIO GABRIEL DA SILVA LIMA'))

    def test_ocr_confidence_recognizes_chupa_nomo_header(self):
        tokens = ['Chupa/Nomo:', '119105', '-', 'FABRICIO', 'GABRIEL', 'DA', 'SILVA', 'LIMA']
        data = {
            'text': tokens,
            'conf': ['88'] * len(tokens),
            'block_num': [1] * len(tokens),
            'par_num': [1] * len(tokens),
            'line_num': [1] * len(tokens),
        }
        self.assertGreater(ns['relevant_header_confidence'](data, '119105'), 0)

    def test_filename_only_is_not_an_ocr_source(self):
        self.assertIsNone(ns['parse_chapa_nome']('Chapa/Nome: ANGELA DA COSTA FERNANDES SILVA Funcao: X', '125530.pdf'))

    def test_no_anchor_does_not_trust_filename(self):
        self.assertIsNone(ns['parse_chapa_nome']('texto aleatorio sem formulario', '125530.pdf'))

    def test_confidence_is_the_plain_average_without_bonus(self):
        tokens = ['Chapa/Nome:', '119105', '-', 'ANA', 'LIMA']
        data = {
            'text': tokens,
            'conf': ['70', '80', '90', '60', '50'],
            'block_num': [1] * 5,
            'par_num': [1] * 5,
            'line_num': [1] * 5,
        }
        self.assertAlmostEqual(ns['relevant_header_confidence'](data, '119105'), 0.70)

    def test_number_before_label_layout(self):
        got = ns['parse_chapa_nome'](
            '126509 KELLY DO CARMO DA SILVA OLIVEIRA Chapa/Nome Data de admissao: 01/09/2025', '126509.pdf'
        )
        self.assertEqual(got[:2], ('126509', 'KELLY DO CARMO DA SILVA OLIVEIRA'))

    def test_year_is_not_used_as_chapa(self):
        self.assertIsNone(ns['parse_chapa_nome']('Fim do Contrato: 01/04/2027 Terça-Feira Domingo', '126509.pdf'))

    def test_ocr_month_with_stray_digit(self):
        self.assertEqual(ns['parse_mes_folha']('FOLHA DE PONTO V2.0 - SETEMBRO0/2026'), 'setembro')


if __name__ == '__main__':
    unittest.main()

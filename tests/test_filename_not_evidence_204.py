import unittest
import _source  # coloca a raiz do projeto no sys.path
from rdf.core import parsing

ns = vars(parsing)


class Tests(unittest.TestCase):
    def test_filename_never_supplies_registration(self):
        self.assertIsNone(ns['parse_chapa_nome']('Chapa/Nome: EMANUELLY OLIVEIRA MOREIRA DOS SANTOS', '120938.jpeg'))

    def test_document_registration_is_used(self):
        result = ns['parse_chapa_nome']('Chapa/Nome: 170938 - EMANUELLY OLIVEIRA MOREIRA DOS SANTOS', '120938.jpeg')
        self.assertEqual(result[0], '170938')
        self.assertEqual(result[3], 'documento')

    def test_dirty_admission_suffix_is_removed(self):
        result = ns['parse_chapa_nome'](
            'Chapa/Nome: 120938 - EMANUELLY OLIVEIRA MOREIRA DOS SANTOS ORTA DO ADMISSAO: 19/05/2025', 'qualquer.jpeg'
        )
        self.assertEqual(result[1], 'EMANUELLY OLIVEIRA MOREIRA DOS SANTOS')

    def test_rounding_matches_status(self):
        self.assertEqual(ns['confidence_percent'](0.716), 72)
        self.assertTrue(ns['is_ready_confidence'](0.716))
        self.assertFalse(ns['is_ready_confidence'](0.714))

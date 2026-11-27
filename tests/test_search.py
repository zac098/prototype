"""Busca de ferramentas: sem diferença de acentos e maiúsculas, com as mais relevantes primeiro."""

import unittest

import _source  # coloca a raiz do projeto no sys.path
from rdf.pdftools.registry import TOOLS, fold, search_tools


def ids(query):
    return [tool.id for tool in search_tools(query)]


class SearchTests(unittest.TestCase):
    def test_accents_and_case_do_not_matter(self):
        self.assertEqual(ids('numeros'), ids('Números'))
        self.assertIn('page-numbers', ids('NUMEROS'))
        self.assertIn('watermark', ids('marca dagua'))

    def test_fold_removes_accents(self):
        self.assertEqual(fold('Declaração Página'), 'declaracao pagina')

    def test_a_title_match_comes_before_a_description_match(self):
        found = ids('pdf')
        self.assertTrue(found)
        first = search_tools('comprimir')[0]
        self.assertEqual(first.id, 'compress')

    def test_every_word_must_match(self):
        self.assertEqual(ids('girar senha'), [])

    def test_prefixes_find_the_tool(self):
        self.assertIn('compress', ids('compr'))
        self.assertIn('protect', ids('prot'))

    def test_empty_query_lists_everything_in_catalog_order(self):
        self.assertEqual(search_tools('   '), list(TOOLS))


if __name__ == '__main__':
    unittest.main()

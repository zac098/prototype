"""Renomeador na 4.0: busca no lote, próximo a revisar (F3), status em pílula, tempo restante, tela vazia e pasta
exportada. As regras ficam em rdf.core.batch (testadas sem interface); a tela, com o leitor falso de test_qt_renamer.
"""

import importlib.util
import os
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import _source  # coloca a raiz do projeto no sys.path
from rdf.core.batch import Batch, fold

HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from rdf.qt.renamer import PILL_TONES, StatusDelegate, format_remaining, pill_tone
    from test_qt_renamer import RenamerCase
else:  # pragma: no cover - sem Qt, só os testes do lote rodam
    RenamerCase = unittest.TestCase


def row(path, status, chapa=None, nome=None, new=''):
    return {'path': path, 'status': status, 'chapa': chapa, 'nome': nome, 'new': new}


class BatchSearchTests(unittest.TestCase):
    def setUp(self):
        self.batch = Batch()
        self.batch.files = ['/a/folha1.pdf', '/a/folha2.pdf', '/a/joao.pdf', '/a/pendente.pdf']
        self.batch.rows = {
            '/a/folha1.pdf': row('/a/folha1.pdf', 'OK', '1001', 'JOÃO DA SILVA', '1001 - JOÃO DA SILVA - MARÇO.PDF'),
            '/a/folha2.pdf': row('/a/folha2.pdf', 'REVISAR', '1002', 'MARIA SOUZA', '1002 - MARIA SOUZA.PDF'),
            '/a/joao.pdf': row('/a/joao.pdf', 'NAO RECONHECIDO'),
        }

    def test_fold_ignores_accents_and_case(self):
        self.assertEqual(fold('JOÃO Março'), 'joao marco')

    def test_text_search_looks_at_names_numbers_and_files(self):
        self.batch.text_filter = 'joao'
        self.assertEqual(self.batch.visible_paths(), ['/a/folha1.pdf', '/a/joao.pdf'])
        self.batch.text_filter = '1002'
        self.assertEqual(self.batch.visible_paths(), ['/a/folha2.pdf'])
        self.batch.text_filter = 'silva marco'  # todas as palavras, em qualquer ordem
        self.assertEqual(self.batch.visible_paths(), ['/a/folha1.pdf'])

    def test_text_search_combines_with_the_status_filter(self):
        self.batch.text_filter = 'folha'
        self.batch.filter_status = 'Revisar'
        self.assertEqual(self.batch.visible_paths(), ['/a/folha2.pdf'])

    def test_next_needing_attention_skips_ready_and_pending_and_wraps(self):
        self.assertEqual(self.batch.attention_count(), 2)
        self.assertEqual(self.batch.next_needing_attention(), '/a/folha2.pdf')
        self.assertEqual(self.batch.next_needing_attention('/a/folha2.pdf'), '/a/joao.pdf')
        self.assertEqual(self.batch.next_needing_attention('/a/joao.pdf'), '/a/folha2.pdf')  # dá a volta
        self.assertIsNone(Batch().next_needing_attention())

    def test_next_needing_attention_respects_the_visible_list(self):
        visible = ['/a/folha1.pdf', '/a/joao.pdf']
        self.assertEqual(self.batch.next_needing_attention(None, visible), '/a/joao.pdf')


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class FormatTests(unittest.TestCase):
    def test_remaining_time_in_short_words(self):
        self.assertEqual(format_remaining(10), 'menos de 1 minuto')
        self.assertEqual(format_remaining(150), 'cerca de 2 min')
        self.assertEqual(format_remaining(3 * 3600 + 5 * 60), 'cerca de 3 h 05 min')

    def test_every_status_has_a_pill_tone(self):
        for status in ('OK', 'APROVADO', 'CORRIGIDO', 'REVISAR', 'ERRO', 'NAO RECONHECIDO', 'Pendente'):
            self.assertIn(pill_tone(status), PILL_TONES)
        self.assertEqual(pill_tone('Pendente'), 'pending')


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class RenamerV4Tests(RenamerCase):
    def setUp(self):
        super().setUp()
        self.files = self.load('folha100.pdf', 'folha200baixa.pdf', 'ruim1.pdf', 'folha300.pdf')
        self.analyze_all()
        self.by_name = {Path(path).name: path for path in self.files}

    def test_an_empty_batch_shows_the_invitation_and_a_loaded_one_the_table(self):
        self.assertIs(self.page.list_stack.currentWidget(), self.page.tree)
        self.page.batch.clear()
        self.page.rebuild_tree()
        self.assertIsNot(self.page.list_stack.currentWidget(), self.page.tree)

    def test_the_status_column_is_painted_as_a_pill(self):
        self.assertIsInstance(self.page.tree.itemDelegateForColumn(4), StatusDelegate)
        self.page.tree.viewport().repaint()  # pinta de verdade (offscreen): nenhum erro no delegate

    def test_searching_hides_the_files_that_do_not_match(self):
        self.page.search_edit.setText('300')
        visible = [path for path, item in self.page.items.items() if not item.isHidden()]
        self.assertEqual(visible, [self.by_name['folha300.pdf']])
        self.assertIn('com "300"', self.page.status_label.text())
        self.page.search_edit.clear()
        self.assertTrue(all(not item.isHidden() for item in self.page.items.values()))

    def test_f3_walks_through_the_files_that_need_review(self):
        self.assertIn('(2)', self.page.next_btn.text())
        first = self.page.select_next_attention()
        self.assertEqual(first, self.by_name['folha200baixa.pdf'])
        self.assertEqual(self.page.selected_paths(), [first])
        second = self.page.select_next_attention()
        self.assertEqual(second, self.by_name['ruim1.pdf'])
        self.assertEqual(self.page.select_next_attention(), first)  # dá a volta

    def test_f3_finds_a_file_hidden_by_the_search(self):
        self.page.search_edit.setText('folha100')
        target = self.page.select_next_attention()
        self.assertEqual(target, self.by_name['folha200baixa.pdf'])
        self.assertEqual(self.page.search_edit.text(), '')  # a busca foi limpa para mostrar o arquivo

    def test_with_nothing_to_review_f3_says_so(self):
        self.select(*self.files)
        self.page.approve_selected()
        self.page.batch.rows[self.by_name['ruim1.pdf']]['status'] = 'OK'
        self.page.update_buttons()
        self.assertFalse(self.page.next_btn.isEnabled())
        self.assertIsNone(self.page.select_next_attention())
        self.assertIn('Nenhum arquivo', self.page.status_label.text())

    def test_the_remaining_time_appears_after_a_few_files(self):
        self.page.analysis_started = 1.0
        self.assertEqual(self.page.remaining_text(1, 10), '')
        self.assertTrue(self.page.remaining_text(5, 10))
        self.assertEqual(self.page.remaining_text(10, 10), '')

    def test_after_exporting_the_folder_can_be_opened(self):
        self.select(self.by_name['ruim1.pdf'])
        self.yes = True
        self.page.remove_selected()
        self.chosen_folder = str(self.tmp / 'saida')
        Path(self.chosen_folder).mkdir()
        self.page.export()
        self.assertFalse(self.page.open_export_btn.isHidden())
        self.assertEqual(self.page.last_export_folder, self.chosen_folder)


if __name__ == '__main__':
    unittest.main()

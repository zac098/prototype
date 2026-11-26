"""Renomeador em Qt: adicionar arquivos, análise, correção, aprovação, exportação, sessão e prévia.

A leitura (OCR) é trocada por um leitor falso e as pastas de dados apontam para uma pasta temporária: nada toca
os dados do usuário. Roda sem janela de verdade (plataforma "offscreen") e é ignorado sem o PySide6.
"""

import importlib.util
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import _source  # coloca a raiz do projeto no sys.path
import fitz
from PIL import Image
from rdf.core import config

HAS_QT = importlib.util.find_spec('PySide6') is not None

if HAS_QT:
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    from rdf.qt.__main__ import create_app
    from rdf.qt.renamer import RenamerPage
    from rdf.qt.window import MainWindow


def make_pdf(path, pages=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for number in range(pages):
        document.new_page(width=595, height=842).insert_text((72, 72), f'pagina {number + 1}')
    document.save(path)
    document.close()
    return str(path)


def fake_analyzer(path, page_index):
    """folha1234.pdf -> folha da matrícula 1234; atestado*.pdf -> atestado; ruim*.pdf -> erro; o resto: não lido."""
    stem = Path(path).stem.lower()
    if stem.startswith('folha'):
        chapa = ''.join(c for c in stem if c.isdigit()) or '1'
        low = stem.endswith('baixa')
        return {
            'category': None,
            'document_type': 'Folha de ponto',
            'parsed': (chapa, f'PESSOA {chapa}', 'MARÇO', 'documento'),
            'method': 'OCR',
            'conf': 0.4 if low else 0.95,
        }
    if stem.startswith('atestado'):
        return {'category': 'Atestados', 'document_type': 'Atestado', 'method': 'Documento', 'conf': 0.9}
    if stem.startswith('ruim'):
        raise RuntimeError('arquivo quebrado')
    return {'category': None, 'document_type': 'x', 'parsed': None, 'method': 'Falhou', 'conf': 0}


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class RenamerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        data = self.tmp / 'appdata'
        self.split_dir, self.convert_dir = data / 'paginas', data / 'convertidos'
        for folder in (self.split_dir, self.convert_dir):
            folder.mkdir(parents=True)
        for name, value in (
            ('SESSION_FILE', data / 'sessao.json'),
            ('SPLIT_DIR', self.split_dir),
            ('CONVERT_DIR', self.convert_dir),
        ):
            patch = mock.patch.object(config, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.page = RenamerPage()
        self.page.resize(1100, 700)
        self.page.show()
        self.addCleanup(self.close_page)
        self.page.analyze_function = fake_analyzer
        self.messages = []
        self.yes = True
        self.multipage_choice = ('keep', 0)
        self.edit_data = None
        self.review_choice = 'proceed'
        self.blocking_choice = 'close'
        self.cancel_choice = 'keep'
        self.chosen_folder = ''
        page = self.page

        def record(kind):
            return lambda title, text='': self.messages.append((kind, title, text))

        page.warn, page.error, page.info = record('warn'), record('error'), record('info')
        page.ask = lambda title, text='': (self.messages.append(('ask', title, text)), self.yes)[1]
        page.ask_multipage = lambda path, total: self.multipage_choice
        page.ask_edit = lambda row: self.edit_data
        page.ask_review_export = lambda review: self.review_choice
        page.ask_blocking_export = lambda problems: self.blocking_choice
        page.ask_cancel_analysis = lambda: self.cancel_choice
        page.choose_folder = lambda title='': self.chosen_folder

    def close_page(self):
        self.page.loader.wait(2000)
        self.page.save_timer.stop()
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    # ---- apoio ----
    def pump(self, seconds=0.05):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)

    def wait_until(self, condition, timeout=10.0):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                self.fail('tempo esgotado esperando a interface')
            self.app.processEvents()
            time.sleep(0.01)

    def load(self, *names, pages=1):
        paths = [make_pdf(self.tmp / 'entrada' / name, pages=pages) for name in names]
        self.page.add_candidates(paths)
        return self.page.batch.files

    def analyze_all(self):
        self.page.start_analysis()
        self.wait_until(lambda: not self.page.analysis_running)

    def select(self, *paths):
        self.page.tree.clearSelection()
        for path in paths:
            self.page.items[path].setSelected(True)

    def status_of(self, path):
        return self.page.batch.status(path)

    def kinds(self):
        return [kind for kind, _title, _text in self.messages]


class LoadingTests(RenamerCase):
    def test_files_are_added_pending_and_the_summary_counts_them(self):
        files = self.load('folha100.pdf', 'folha200.pdf')
        self.assertEqual(len(files), 2)
        self.assertEqual(self.page.tree.topLevelItemCount(), 2)
        self.assertEqual(self.page.tree.topLevelItem(0).text(4), 'Pendente')
        self.assertEqual(self.page.summary_label.text(), '2 arquivos  |  0 prontos  |  0 para revisar  |  2 bloqueados')
        self.assertIn('2 arquivo(s) adicionado(s). Total: 2.', self.page.status_label.text())

    def test_adding_the_same_files_again_does_nothing(self):
        files = self.load('folha100.pdf')
        self.page.add_candidates(files)
        self.assertEqual(len(self.page.batch.files), 1)
        self.assertIn('já estão no lote', self.page.status_label.text())

    def test_images_are_converted_to_pdf_and_keep_their_original(self):
        image = self.tmp / 'entrada' / 'foto.png'
        image.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (300, 400), 'white').save(image)
        self.page.add_candidates([image])
        (path,) = self.page.batch.files
        self.assertEqual(Path(path).parent, self.convert_dir)
        self.assertEqual(self.page.batch.source(path), str(image))
        self.assertIn(path, self.page.batch.generated_files)
        self.assertEqual(self.page.tree.topLevelItem(0).text(0), 'foto.png')

    def test_a_fake_pdf_is_rejected_with_a_message(self):
        fake = self.tmp / 'entrada' / 'falso.pdf'
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_bytes(b'nao sou pdf')
        self.page.add_candidates([fake])
        self.assertEqual(self.page.batch.files, [])
        self.assertEqual(self.kinds(), ['error'])
        self.assertIn('falso.pdf', self.messages[0][2])

    def test_a_multipage_pdf_can_be_split_kept_or_ignored(self):
        self.multipage_choice = ('split', 0)
        self.load('varias.pdf', pages=3)
        self.assertEqual(len(self.page.batch.files), 3)
        self.assertTrue(all(Path(p).parent == self.split_dir for p in self.page.batch.files))
        self.assertEqual({Path(self.page.batch.source(p)).name for p in self.page.batch.files}, {'varias.pdf'})
        self.assertEqual(len(self.page.batch.generated_files), 3)

        self.page.batch.clear()
        self.page.rebuild_tree()
        self.multipage_choice = ('keep', 2)
        (kept,) = self.load('outra.pdf', pages=3)
        self.assertEqual(self.page.batch.analysis_pages[kept], 2)

        self.page.batch.clear()
        self.page.rebuild_tree()
        self.multipage_choice = ('ignore', 0)
        self.assertEqual(self.load('ignorada.pdf', pages=3), [])

    def test_the_batch_limits_stop_oversized_batches(self):
        with mock.patch.object(config, 'MAX_BATCH_FILES', 1):
            self.load('a.pdf', 'b.pdf')
        self.assertEqual(self.page.batch.files, [])
        self.assertEqual(self.messages[0][:2], ('error', 'Limite do lote'))

    def test_large_files_ask_before_continuing(self):
        self.yes = False
        with mock.patch.object(config, 'LARGE_FILE_WARNING_MB', 0):
            self.load('a.pdf')
        self.assertEqual(self.page.batch.files, [])
        self.assertEqual(self.messages[0][:2], ('ask', 'Arquivos grandes'))

    def test_dropping_files_adds_them_and_unsupported_drops_warn(self):
        def drop(paths):
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
            self.page.dropEvent(QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))

        pdf = make_pdf(self.tmp / 'solto' / 'folha1.pdf')
        drop([pdf])
        self.assertEqual(len(self.page.batch.files), 1)
        notes = self.tmp / 'solto' / 'notas.txt'
        notes.write_text('x')
        drop([notes])
        self.assertEqual(self.kinds(), ['warn'])

    def test_dropping_is_ignored_while_analyzing(self):
        self.page.analysis_running = True
        self.page.dropEvent(QDropEvent(QPointF(5, 5), Qt.CopyAction, QMimeData(), Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(self.messages, [])
        self.page.analysis_running = False


class AnalysisTests(RenamerCase):
    def test_every_kind_of_result_becomes_a_row(self):
        files = self.load('folha100.pdf', 'folha200baixa.pdf', 'atestado1.pdf', 'ruim1.pdf', 'outro.pdf')
        self.analyze_all()
        by_name = {Path(p).name: p for p in files}
        batch = self.page.batch
        self.assertEqual(batch.status(by_name['folha100.pdf']), 'OK')
        self.assertEqual(batch.new_name(by_name['folha100.pdf']), '100 - PESSOA 100 - MARÇO.PDF')
        self.assertEqual(batch.status(by_name['folha200baixa.pdf']), 'REVISAR')
        self.assertEqual(batch.status(by_name['atestado1.pdf']), 'OK')
        self.assertEqual(batch.rows[by_name['atestado1.pdf']]['category'], 'Atestados')
        self.assertEqual(batch.status(by_name['ruim1.pdf']), 'ERRO')
        self.assertEqual(batch.status(by_name['outro.pdf']), 'NAO RECONHECIDO')
        self.assertEqual(self.page.summary_label.text(), '5 arquivos  |  2 prontos  |  1 para revisar  |  2 bloqueados')
        self.assertEqual(self.page.items[by_name['folha100.pdf']].text(3), '95%')
        self.assertEqual(self.page.items[by_name['atestado1.pdf']].text(3), 'N/A')
        self.assertEqual(self.page.progress.value(), 5)
        self.assertFalse(self.page.analysis_running)
        self.assertTrue(self.page.analyze_btn.isEnabled())
        self.assertFalse(self.page.cancel_btn.isEnabled())

    def test_nothing_to_analyze_warns(self):
        self.page.start_analysis()
        self.assertEqual(self.messages[0][:2], ('warn', 'Aviso'))
        self.page.start_analysis(selected_only=True)
        self.assertEqual(len(self.messages), 2)

    def test_controls_are_locked_while_analyzing_and_come_back(self):
        gate = threading.Event()

        def slow(path, page_index):
            gate.wait(5)
            return fake_analyzer(path, page_index)

        self.page.analyze_function = slow
        self.load('folha1.pdf')
        self.page.start_analysis()
        self.assertTrue(self.page.analysis_running)
        self.assertFalse(self.page.analyze_btn.isEnabled())
        self.assertFalse(self.page.export_btn.isEnabled())
        self.assertFalse(self.page.chapa_check.isEnabled())
        self.assertTrue(self.page.cancel_btn.isEnabled())
        self.page.approve_selected()
        self.assertEqual(self.messages[-1][1], 'Análise em andamento')
        gate.set()
        self.wait_until(lambda: not self.page.analysis_running)
        self.assertTrue(self.page.export_btn.isEnabled())

    def test_verifying_selected_files_only_rereads_those(self):
        files = self.load('folha1.pdf', 'folha2.pdf')
        self.analyze_all()
        calls = []
        self.page.analyze_function = lambda path, page_index: (
            calls.append(Path(path).name),
            fake_analyzer(path, page_index),
        )[1]
        self.select(files[1])
        self.page.start_analysis(selected_only=True)
        self.wait_until(lambda: not self.page.analysis_running)
        self.assertEqual(calls, ['folha2.pdf'])
        self.assertEqual(self.status_of(files[0]), 'OK')

    def test_cancelling_and_keeping_results_leaves_the_rest_pending(self):
        files = self.load(*[f'folha{n}.pdf' for n in range(1, 9)])
        started = threading.Event()
        release = threading.Event()

        def blocking(path, page_index):
            started.set()
            release.wait(5)
            return fake_analyzer(path, page_index)

        self.page.analyze_function = blocking
        self.page.start_analysis()
        self.wait_until(started.is_set)
        self.cancel_choice = 'keep'
        self.page.request_cancel_analysis()
        self.assertFalse(self.page.cancel_btn.isEnabled())
        self.assertIn('Cancelamento solicitado', self.page.status_label.text())
        release.set()
        self.wait_until(lambda: not self.page.analysis_running)
        done = [p for p in files if self.status_of(p) != 'Pendente']
        self.assertTrue(0 < len(done) < len(files))
        self.assertIn('Análise cancelada.', self.page.status_label.text())
        self.assertEqual(self.messages[-1][:2], ('info', 'Análise cancelada'))

    def test_cancelling_and_discarding_restores_the_previous_state(self):
        files = self.load('folha1.pdf', 'folha2.pdf')
        self.analyze_all()
        release = threading.Event()
        started = threading.Event()

        def blocking(path, page_index):
            started.set()
            release.wait(5)
            return {'category': None, 'document_type': 'x', 'parsed': None, 'method': 'Falhou', 'conf': 0}

        self.page.analyze_function = blocking
        self.page.start_analysis()
        self.wait_until(started.is_set)
        self.cancel_choice = 'discard'
        self.page.request_cancel_analysis()
        release.set()
        self.wait_until(lambda: not self.page.analysis_running)
        self.assertEqual([self.status_of(p) for p in files], ['OK', 'OK'])
        self.assertIn('estado anterior foi restaurado', self.page.status_label.text())

    def test_choosing_to_continue_does_not_cancel(self):
        self.load('folha1.pdf')
        gate = threading.Event()
        self.page.analyze_function = lambda path, page_index: (gate.wait(5), fake_analyzer(path, page_index))[1]
        self.page.start_analysis()
        self.cancel_choice = 'continue'
        self.page.request_cancel_analysis()
        self.assertFalse(self.page.cancel_event.is_set())
        gate.set()
        self.wait_until(lambda: not self.page.analysis_running)
        self.assertIn('Análise concluída', self.page.status_label.text())


class ActionTests(RenamerCase):
    def setUp(self):
        super().setUp()
        self.files = self.load('folha100.pdf', 'folha200baixa.pdf', 'ruim1.pdf')
        self.analyze_all()
        self.ok, self.review, self.bad = (
            self.files
            if Path(self.files[0]).name == 'folha100.pdf'
            else sorted(
                self.files, key=lambda p: ['folha100.pdf', 'folha200baixa.pdf', 'ruim1.pdf'].index(Path(p).name)
            )
        )

    def test_approving_marks_selected_ready_files_and_skips_blocked_ones(self):
        self.select(self.review, self.bad)
        self.page.approve_selected()
        self.assertEqual((self.status_of(self.review), self.status_of(self.bad)), ('APROVADO', 'ERRO'))
        self.assertEqual(self.page.items[self.review].text(4), 'APROVADO')
        self.assertIn('1 arquivo(s) aprovado(s).', self.page.status_label.text())

    def test_approving_as_a_certificate_names_it_from_the_original_file(self):
        self.select(self.bad)
        self.page.approve_as_category('Declarações')
        row = self.page.batch.rows[self.bad]
        self.assertEqual((row['status'], row['category']), ('APROVADO', 'Declarações'))
        self.assertIn('DECLARAÇÃO', row['new'])
        self.assertEqual(self.page.items[self.bad].text(3), 'N/A')
        self.assertEqual(self.status_of(self.bad), 'APROVADO')

    def test_actions_without_a_selection_warn(self):
        self.select()
        for action in (
            self.page.approve_selected,
            lambda: self.page.approve_as_category('Atestados'),
            self.page.mark_for_review,
        ):
            action()
        self.assertEqual(self.kinds(), ['warn', 'warn', 'warn'])

    def test_marking_for_review(self):
        self.select(self.ok)
        self.page.mark_for_review()
        self.assertEqual(self.status_of(self.ok), 'REVISAR')

    def test_editing_a_file_corrects_its_data(self):
        self.select(self.review)
        self.edit_data = {'chapa': '999', 'nome': 'JOÃO DA SILVA', 'mes': 'ABRIL'}
        self.page.edit_selected()
        self.assertEqual(self.status_of(self.review), 'CORRIGIDO')
        self.assertEqual(self.page.items[self.review].text(1), '999 - JOÃO DA SILVA - ABRIL.PDF')
        self.assertEqual(self.page.items[self.review].text(2), 'Manual')

    def test_cancelling_the_edit_changes_nothing(self):
        self.select(self.review)
        self.edit_data = None
        self.page.edit_selected()
        self.assertEqual(self.status_of(self.review), 'REVISAR')

    def test_editing_needs_exactly_one_file(self):
        self.select(self.ok, self.review)
        self.page.edit_selected()
        self.assertEqual(self.messages[-1][:2], ('warn', 'Seleção'))
        self.assertFalse(self.page.edit_btn.isEnabled())

    def test_the_filter_hides_files_and_keeps_the_counts(self):
        self.page.filter_combo.setCurrentText('Revisar')
        self.page.on_filter_changed('Revisar')
        visible = [p for p, item in self.page.items.items() if not item.isHidden()]
        self.assertEqual(visible, [self.review])
        self.assertIn('Filtro Revisar: 1 de 3', self.page.status_label.text())
        self.page.on_filter_changed('Todos')
        self.assertTrue(all(not item.isHidden() for item in self.page.items.values()))

    def test_filtering_away_the_selected_file_unselects_it(self):
        self.select(self.ok)
        self.page.on_filter_changed('Bloqueados')
        self.assertEqual(self.page.selected_paths(), [])

    def test_naming_options_rename_everything_without_touching_approvals(self):
        self.select(self.review)
        self.page.approve_selected()
        self.page.nome_check.setChecked(False)
        self.page.mes_check.setChecked(False)
        self.page.on_naming_changed()
        self.assertEqual(self.page.items[self.ok].text(1), '100.PDF')
        self.assertEqual(self.status_of(self.review), 'APROVADO')
        self.assertFalse(self.page.batch.include_nome)

    def test_changing_the_format_renames_and_says_so(self):
        self.page.format_combo.setCurrentText('PNG')
        self.page.on_format_changed('PNG')
        self.assertTrue(self.page.items[self.ok].text(1).endswith('.PNG'))
        self.assertEqual(self.page.status_label.text(), 'Formato de exportação: PNG.')

    def test_removing_files_asks_first_and_cleans_temporaries(self):
        self.yes = False
        self.select(self.ok)
        self.page.remove_selected()
        self.assertIn(self.ok, self.page.batch.files)
        self.yes = True
        self.page.remove_selected()
        self.assertNotIn(self.ok, self.page.batch.files)
        self.assertEqual(self.page.tree.topLevelItemCount(), 2)
        self.assertEqual(Path(self.ok).exists(), True)  # o original do usuário nunca é apagado

    def test_copy_actions_use_the_clipboard(self):
        from PySide6.QtWidgets import QApplication

        self.select(self.ok)
        self.page.copy_selected_new_name()
        self.assertEqual(QApplication.clipboard().text(), '100 - PESSOA 100 - MARÇO.PDF')
        self.page.copy_selected_path()
        self.assertEqual(QApplication.clipboard().text(), self.ok)
        self.select(self.bad)
        self.page.copy_selected_new_name()
        self.assertEqual(self.messages[-1][1], 'Copiar novo nome')


class ExportTests(RenamerCase):
    def setUp(self):
        super().setUp()
        self.out = self.tmp / 'saida'
        self.out.mkdir()
        self.chosen_folder = str(self.out)

    def test_exporting_copies_files_with_their_new_names_and_ends_the_session(self):
        self.load('folha100.pdf', 'atestado1.pdf')
        self.analyze_all()
        self.page.save_now()
        self.assertTrue(config.SESSION_FILE.exists())
        self.page.export()
        self.assertEqual(
            sorted(p.name for p in self.out.rglob('*') if p.is_file()),
            ['100 - PESSOA 100 - MARÇO.PDF', 'ATESTADO1 - ATESTADO.PDF'],
        )
        self.assertTrue((self.out / 'Atestados' / 'ATESTADO1 - ATESTADO.PDF').exists())
        self.assertEqual(self.messages[-1][:2], ('info', 'Concluído'))
        self.assertIn('Atestados: 1', self.messages[-1][2])
        self.assertFalse(config.SESSION_FILE.exists())
        self.assertTrue(self.page.batch.persistence_disabled)

    def test_exporting_with_nothing_loaded_warns(self):
        self.page.export()
        self.assertEqual(self.kinds(), ['warn'])

    def test_blocked_files_stop_the_export_and_can_be_shown(self):
        files = self.load('folha100.pdf', 'ruim1.pdf')
        self.analyze_all()
        self.blocking_choice = 'show'
        self.page.export()
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertEqual(self.page.batch.filter_status, 'Bloqueados')
        self.assertEqual(self.page.filter_combo.currentText(), 'Bloqueados')
        bad = next(p for p in files if p.endswith('ruim1.pdf'))
        self.assertEqual(self.page.selected_paths(), [bad])
        self.assertIn('bloqueado(s) destacados em vermelho', self.page.status_label.text())

    def test_closing_the_blocking_dialog_only_reports(self):
        self.load('ruim1.pdf')
        self.analyze_all()
        self.blocking_choice = 'close'
        self.page.export()
        self.assertIn('Exportação bloqueada: 1 arquivo(s)', self.page.status_label.text())

    def test_files_to_review_can_be_reviewed_exported_or_cancelled(self):
        files = self.load('folha100baixa.pdf')
        self.analyze_all()
        self.review_choice = 'review'
        self.page.export()
        self.assertEqual(self.page.batch.filter_status, 'Revisar')
        self.assertEqual(self.page.selected_paths(), files)
        self.assertEqual(list(self.out.iterdir()), [])
        self.review_choice = 'cancel'
        self.page.export()
        self.assertEqual(self.page.status_label.text(), 'Exportação cancelada pelo usuário.')
        self.review_choice = 'proceed'
        self.page.export()
        self.assertEqual(len(list(self.out.iterdir())), 1)
        self.assertIn('Incluídos com aviso: 1', self.messages[-1][2])

    def test_choosing_no_folder_cancels(self):
        self.load('folha100.pdf')
        self.analyze_all()
        self.chosen_folder = ''
        self.page.export()
        self.assertEqual(self.page.status_label.text(), 'Exportação cancelada.')
        self.assertFalse(self.page.batch.persistence_disabled)

    def test_a_partial_failure_keeps_the_session_and_says_which_files_failed(self):
        self.load('folha100.pdf', 'folha200.pdf')
        self.analyze_all()
        real = __import__('rdf.core.exporter', fromlist=['x']).export_source
        first = self.page.batch.files[0]

        def flaky(source, target, fmt):
            if source == first:
                raise OSError('disco cheio')
            return real(source, target, fmt)

        with mock.patch('rdf.core.exporter.export_source', flaky):
            self.page.export()
        self.assertEqual(self.messages[-1][:2], ('error', 'Exportação parcial'))
        self.assertIn('folha100.pdf', self.messages[-1][2])
        self.assertFalse(self.page.batch.persistence_disabled)

    def test_images_are_exported_one_per_page(self):
        self.load('folha100.pdf', pages=1)
        self.analyze_all()
        self.page.format_combo.setCurrentText('PNG')
        self.page.on_format_changed('PNG')
        self.page.export()
        self.assertEqual([p.name for p in self.out.iterdir()], ['100 - PESSOA 100 - MARÇO.PNG'])


class SessionTests(RenamerCase):
    def test_changes_are_saved_after_a_short_pause_and_restored_on_the_next_start(self):
        files = self.load('folha100.pdf', 'folha200baixa.pdf')
        self.analyze_all()
        self.page.nome_check.setChecked(False)
        self.page.on_naming_changed()
        self.assertTrue(self.page.save_timer.isActive())
        self.wait_until(lambda: config.SESSION_FILE.exists() and not self.page.save_timer.isActive())

        again = RenamerPage()
        self.addCleanup(again.deleteLater)
        again.ask = lambda title, text='': True
        again.offer_restore_session()
        self.assertEqual(again.batch.files, files)
        self.assertEqual(again.batch.options, (True, False, True))
        self.assertEqual(again.tree.topLevelItemCount(), 2)
        self.assertEqual(again.batch.status(files[0]), 'OK')
        self.assertFalse(again.nome_check.isChecked())
        self.assertIn('Sessão recuperada: 2 arquivo(s).', again.status_label.text())

    def test_declining_to_restore_discards_the_session(self):
        self.load('folha100.pdf')
        self.page.save_now()
        other = RenamerPage()
        self.addCleanup(other.deleteLater)
        other.ask = lambda title, text='': False
        other.offer_restore_session()
        self.assertEqual(other.batch.files, [])
        self.assertFalse(config.SESSION_FILE.exists())

    def test_a_damaged_session_is_discarded_with_a_warning(self):
        config.SESSION_FILE.write_text('{ quebrado', encoding='utf-8')
        self.page.offer_restore_session()
        self.assertEqual(self.messages[-1][:2], ('warn', 'Sessão descartada'))
        self.assertFalse(config.SESSION_FILE.exists())

    def test_a_session_without_existing_files_is_ignored(self):
        self.load('folha100.pdf')
        self.page.save_now()
        Path(self.page.batch.files[0]).unlink()
        other = RenamerPage()
        self.addCleanup(other.deleteLater)
        other.offer_restore_session()
        self.assertEqual(other.batch.files, [])

    def test_clearing_the_session_empties_the_batch_and_the_saved_file(self):
        self.load('folha100.pdf')
        self.page.save_now()
        self.page.clear_session_data()
        self.assertEqual(self.page.batch.files, [])
        self.assertEqual(self.page.tree.topLevelItemCount(), 0)
        self.assertFalse(config.SESSION_FILE.exists())
        self.assertTrue(self.page.batch.persistence_disabled)

    def test_closing_saves_the_session_unless_the_batch_was_exported(self):
        self.load('folha100.pdf')
        self.assertTrue(self.page.prepare_close())
        self.assertTrue(config.SESSION_FILE.exists())
        self.page.batch.persistence_disabled = True
        config.SESSION_FILE.unlink()
        self.assertTrue(self.page.prepare_close())
        self.assertFalse(config.SESSION_FILE.exists())

    def test_it_cannot_close_in_the_middle_of_an_analysis(self):
        self.page.analysis_running = True
        self.assertFalse(self.page.prepare_close())
        self.assertEqual(self.messages[-1][:2], ('warn', 'Análise em andamento'))
        self.assertFalse(self.page.prepare_close())  # o aviso não repete a cada tentativa
        self.assertEqual(self.kinds().count('warn'), 1)
        self.page.analysis_running = False


class PreviewTests(RenamerCase):
    def test_selecting_a_file_loads_its_page_in_the_background(self):
        (path,) = self.load('folha100.pdf', pages=1)
        self.select(path)
        self.page.show_selected()
        self.wait_until(lambda: self.page.preview.has_image())
        self.assertEqual(self.page.page_label.text(), 'Página 1 de 1')
        self.assertEqual(self.page.preview_path, path)
        self.assertFalse(self.page.prev_page_btn.isEnabled())

    def test_pages_of_a_kept_multipage_pdf_can_be_browsed(self):
        self.multipage_choice = ('keep', 1)
        (path,) = self.load('varias.pdf', pages=3)
        self.select(path)
        self.page.show_selected()
        self.wait_until(lambda: self.page.preview_total == 3)
        self.assertEqual(self.page.page_label.text(), 'Página 2 de 3')  # a página escolhida para a leitura
        self.assertTrue(self.page.prev_page_btn.isEnabled() and self.page.next_page_btn.isEnabled())
        self.page.change_page(1)
        self.wait_until(lambda: self.page.page_label.text() == 'Página 3 de 3')
        self.assertFalse(self.page.next_page_btn.isEnabled())
        self.page.change_page(1)
        self.assertEqual(self.page.preview_page, 2)

    def test_zoom_and_fit(self):
        (path,) = self.load('folha100.pdf')
        self.select(path)
        self.page.show_selected()
        self.wait_until(lambda: self.page.preview.has_image())
        fitted = self.page.preview.zoom
        self.assertTrue(self.page.preview.fitted)
        self.page.preview.zoom_by(1.2)
        self.assertGreater(self.page.preview.zoom, fitted)
        self.assertFalse(self.page.preview.fitted)
        self.assertEqual(self.page.zoom_label.text(), f'{self.page.preview.zoom:.0%}')
        self.page.preview.zoom_by(1 / 1.2 / 1.2)  # nunca menor que a página ajustada
        self.assertAlmostEqual(self.page.preview.zoom, self.page.preview.min_zoom)
        self.page.preview.zoom_by(1000)
        self.assertEqual(self.page.preview.zoom, 4.0)
        self.page.fit_btn.click()
        self.assertTrue(self.page.preview.fitted)

    def test_a_broken_pdf_shows_the_error_instead_of_a_page(self):
        (path,) = self.load('folha100.pdf')
        Path(path).write_bytes(b'quebrado')
        self.select(path)
        self.page.show_selected()
        self.wait_until(lambda: self.page.page_label.text() == 'Página 0 de 0' and self.page.preview_total == 0)
        self.pump(0.3)
        self.assertFalse(self.page.preview.has_image())

    def test_removing_the_previewed_file_clears_the_preview(self):
        (path,) = self.load('folha100.pdf')
        self.select(path)
        self.page.show_selected()
        self.wait_until(lambda: self.page.preview.has_image())
        self.page.remove_selected()
        self.assertIsNone(self.page.preview_path)
        self.assertFalse(self.page.preview.has_image())


class LayoutTests(RenamerCase):
    def test_a_narrow_window_drops_the_extra_columns_and_shortens_texts(self):
        self.page.resize(780, 520)
        self.app.processEvents()
        self.assertTrue(self.page.tree.isColumnHidden(2) and self.page.tree.isColumnHidden(3))
        self.assertEqual(self.page.select_files_btn.text(), 'Adicionar')
        self.assertEqual(self.page.select_folder_btn.text(), 'Pasta')
        self.assertEqual(self.page.edit_btn.text(), 'Editar')
        self.assertTrue(self.page.order_hint.isHidden() and self.page.tip_label.isHidden())
        self.page.resize(1346, 688)
        self.app.processEvents()
        self.assertFalse(self.page.tree.isColumnHidden(2))
        self.assertEqual(self.page.select_files_btn.text(), 'Adicionar arquivos')
        self.assertFalse(self.page.order_hint.isHidden() or self.page.tip_label.isHidden())

    def test_the_three_steps_are_numbered(self):
        from PySide6.QtWidgets import QLabel

        captions = [label.text() for label in self.page.findChildren(QLabel) if label.objectName() == 'caption']
        self.assertEqual(captions, ['1 · Adicionar', '2 · Analisar', '3 · Aprovar e exportar'])

    def test_the_toolbar_buttons_share_one_height(self):
        heights = {
            button.height()
            for button in (
                self.page.select_files_btn,
                self.page.analyze_btn,
                self.page.verify_btn,
                self.page.approve_btn,
                self.page.export_btn,
            )
        }
        self.assertEqual(heights, {40})


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest('PySide6 não instalado')
        cls.app = create_app([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        data = Path(self._tmp.name)
        for name, value in (('SESSION_FILE', data / 's.json'), ('SPLIT_DIR', data), ('CONVERT_DIR', data)):
            patch = mock.patch.object(config, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.window = MainWindow()
        self.window.show()
        self.addCleanup(self.window.deleteLater)

    def test_the_renamer_offers_to_restore_a_session_the_first_time_it_opens(self):
        with mock.patch.object(RenamerPage, 'offer_restore_session') as offer:
            self.window.open_tool('renamer')
            deadline = time.monotonic() + 3
            while not offer.called and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.window.show_home()
            self.window.open_tool('renamer')
            self.app.processEvents()
        offer.assert_called_once()

    def test_the_window_will_not_close_during_an_analysis(self):
        page = self.window.open_tool('renamer')
        page.analysis_running = True
        with mock.patch.object(RenamerPage, 'warn') as warn:
            self.assertFalse(self.window.close())
        warn.assert_called_once()
        page.analysis_running = False
        self.assertTrue(self.window.close())

    def open_with_files(self, *names):
        page = self.window.open_tool('renamer')
        page.analyze_function = fake_analyzer
        files = [make_pdf(Path(self._tmp.name) / 'entrada' / name) for name in names]
        page.batch.load(files)
        page.rebuild_tree()
        return page, files

    def test_a_loaded_batch_asks_before_leaving_and_staying_keeps_it(self):
        page, files = self.open_with_files('folha1.pdf')
        self.assertTrue(page.has_unsaved_work())
        with mock.patch.object(self.window, 'ask_unsaved_to_leave', return_value='stay') as ask:
            self.assertFalse(self.window.request_home())
        self.assertIn('ainda não foram exportados', page.unsaved_text())
        ask.assert_called_once_with(page)
        self.assertEqual(page.batch.files, files)

    def test_leaving_without_saving_resets_the_renamer_and_drops_the_session(self):
        page, _files = self.open_with_files('folha1.pdf')
        page.batch.save_session()
        self.assertTrue(config.SESSION_FILE.exists())
        with mock.patch.object(self.window, 'ask_unsaved_to_leave', return_value='discard'):
            self.assertTrue(self.window.request_home())
        self.assertFalse(config.SESSION_FILE.exists())
        self.assertNotIn('renamer', self.window.pages)
        with mock.patch.object(RenamerPage, 'offer_restore_session'):
            fresh = self.window.open_tool('renamer')
        self.assertIsNot(fresh, page)
        self.assertEqual(fresh.batch.files, [])

    def test_exporting_from_the_leave_dialog_leaves_only_if_it_worked(self):
        page, _files = self.open_with_files('folha1.pdf')

        def export_fails():
            return None  # o usuário desistiu da pasta: o lote continua sem exportar

        with (
            mock.patch.object(self.window, 'ask_unsaved_to_leave', return_value='save'),
            mock.patch.object(page, 'export', side_effect=export_fails) as export,
        ):
            self.assertFalse(self.window.request_home())
        export.assert_called_once()
        self.assertEqual(self.window.current_id, 'renamer')

        def export_works():
            page.batch.persistence_disabled = True  # é o que uma exportação completa faz

        with (
            mock.patch.object(self.window, 'ask_unsaved_to_leave', return_value='save'),
            mock.patch.object(page, 'export', side_effect=export_works),
        ):
            self.assertTrue(self.window.request_home())
        self.assertIsNone(self.window.current_id)

    def test_an_exported_or_empty_batch_leaves_without_asking(self):
        page = self.window.open_tool('renamer')
        self.assertFalse(page.has_unsaved_work())
        with mock.patch.object(self.window, 'ask_unsaved_to_leave') as ask:
            self.assertTrue(self.window.request_home())
        ask.assert_not_called()

    def test_leaving_during_an_analysis_cancels_it_and_waits_for_it_to_stop(self):
        page, _files = self.open_with_files('folha1.pdf', 'folha2.pdf')
        gate = threading.Event()

        def slow(path, page_index):
            gate.wait(5)
            return fake_analyzer(path, page_index)

        page.analyze_function = slow
        page.start_analysis()
        self.assertTrue(page.running)
        with mock.patch.object(self.window, 'ask_cancel_to_leave', return_value=False):
            self.assertFalse(self.window.request_home())
        self.assertTrue(page.running)
        threading.Timer(0.3, gate.set).start()  # a leitura em curso termina logo depois do pedido
        with mock.patch.object(self.window, 'ask_cancel_to_leave', return_value=True):
            self.assertTrue(self.window.request_home())
        self.assertIsNone(self.window.current_id)
        self.assertNotIn('renamer', self.window.pages)
        self.assertFalse(page.running)
        self.assertFalse(config.SESSION_FILE.exists())


if __name__ == '__main__':
    unittest.main()

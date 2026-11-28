"""Lote do renomeador, entrada de arquivos, análise em paralelo e exportação: tudo sem interface."""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import _source  # coloca a raiz do projeto no sys.path
import fitz
from PIL import Image
from rdf.core import analysis_runner, batch, config, exporter, inputs


def make_pdf(path, pages=1, text=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for number in range(pages):
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 72), text or f'pagina {number + 1}')
    document.save(path)
    document.close()
    return str(path)


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.data = self.tmp / 'appdata'
        self.split_dir = self.data / 'paginas'
        self.convert_dir = self.data / 'convertidos'
        for folder in (self.split_dir, self.convert_dir):
            folder.mkdir(parents=True)
        for name, value in (
            ('SESSION_FILE', self.data / 'sessao.json'),
            ('SPLIT_DIR', self.split_dir),
            ('CONVERT_DIR', self.convert_dir),
        ):
            patch = mock.patch.object(config, name, value)
            patch.start()
            self.addCleanup(patch.stop)


def timesheet_result(chapa='12345', nome='ANA SILVA', mes='MARÇO 2026', conf=0.95, source='documento'):
    return {
        'category': None,
        'document_type': 'Folha de ponto',
        'parsed': (chapa, nome, mes, source),
        'method': 'OCR',
        'conf': conf,
    }


class NamingTests(unittest.TestCase):
    def test_parts_follow_the_chosen_options(self):
        row = {'chapa': '123', 'nome': 'ANA', 'mes': 'MARÇO', 'path': 'x.pdf'}
        self.assertEqual(batch.compose_filename(row, (True, True, True)), '123 - ANA - MARÇO.PDF')
        self.assertEqual(batch.compose_filename(row, (True, False, True)), '123 - MARÇO.PDF')
        self.assertEqual(batch.compose_filename(row, (False, True, False), 'jpg'), 'ANA.JPG')

    def test_without_any_part_it_falls_back_to_the_original_name(self):
        row = {'path': 'C:/pasta/folha antiga.pdf'}
        self.assertEqual(batch.compose_filename(row, (True, True, True)), 'FOLHA ANTIGA.PDF')
        self.assertEqual(
            batch.compose_filename(
                row, (True, True, True), original_sources={'C:/pasta/folha antiga.pdf': 'D:/foto 1.jpg'}
            ),
            'FOTO 1.PDF',
        )

    def test_unsafe_characters_never_reach_the_name(self):
        row = {'chapa': '1', 'nome': 'A/B:C*D', 'mes': None, 'path': 'x.pdf'}
        name = batch.compose_filename(row, (True, True, False))
        self.assertNotRegex(name, r'[\\/:*?"<>|]')

    def test_output_extension(self):
        self.assertEqual(
            [batch.output_extension(f) for f in ('PDF', 'jpeg', 'JPG', 'png', 'xyz', None)],
            ['pdf', 'jpg', 'jpg', 'png', 'pdf', 'pdf'],
        )
        self.assertEqual(batch.with_output_extension('abc.pdf', 'PNG'), 'ABC.PNG')
        self.assertEqual(batch.with_output_extension('', 'PNG'), '')

    def test_status_tones_and_blocking(self):
        self.assertEqual(
            [batch.status_tone(s) for s in ('OK', 'corrigido', 'APROVADO', 'ERRO', 'REVISAR', 'Pendente')],
            ['ok', 'ok', 'approved', 'error', 'review', 'review'],
        )
        self.assertTrue(all(batch.is_blocking_status(s) for s in ('Pendente', 'erro', 'NAO RECONHECIDO', 'FALHOU')))
        self.assertFalse(any(batch.is_blocking_status(s) for s in ('OK', 'REVISAR', 'APROVADO', None)))


class RowTests(unittest.TestCase):
    def build(self, result, options=(True, True, True), fmt='PDF'):
        return batch.row_from_result('a.pdf', result, options, fmt, {}, page=2)

    def test_a_good_timesheet_is_ready(self):
        row = self.build(timesheet_result())
        self.assertEqual(
            (row['status'], row['new'], row['analysis_page']), ('OK', '12345 - ANA SILVA - MARÇO 2026.PDF', 2)
        )

    def test_low_confidence_or_missing_fields_need_review(self):
        self.assertEqual(self.build(timesheet_result(conf=0.4))['status'], 'REVISAR')
        self.assertEqual(self.build(timesheet_result(mes=None))['status'], 'REVISAR')
        self.assertEqual(self.build(timesheet_result(mes=None), options=(True, True, False))['status'], 'OK')
        self.assertEqual(self.build(timesheet_result(source='nome do arquivo'))['status'], 'REVISAR')

    def test_certificates_are_classified_without_inventing_fields(self):
        result = {'category': 'Atestados', 'document_type': 'Atestado', 'method': 'Documento', 'conf': 0.9}
        row = self.build(result)
        self.assertEqual((row['status'], row['category'], row['chapa']), ('OK', 'Atestados', None))
        self.assertTrue(row['new'].endswith('.PDF'))
        self.assertIn('ATESTADO', row['new'])

    def test_an_unrecognized_file_is_blocked(self):
        row = self.build({'category': None, 'parsed': None, 'method': 'Falhou', 'conf': 0, 'document_type': 'x'})
        self.assertEqual((row['status'], row['new']), ('NAO RECONHECIDO', ''))

    def test_error_rows_carry_a_short_message(self):
        row = batch.error_row('a.pdf', 'x' * 500)
        self.assertEqual((row['status'], row['method'], len(row['error'])), ('ERRO', 'Erro', 300))


class BatchTests(TempCase):
    def make_batch(self, names=('b.pdf', 'a.pdf', 'c.pdf')):
        lote = batch.Batch()
        lote.load([make_pdf(self.tmp / name) for name in names] + [str(self.tmp / 'nota.txt')])
        return lote

    def analyze(self, lote, path, **kwargs):
        row = batch.row_from_result(
            path, timesheet_result(**kwargs), lote.options, lote.output_format, lote.original_sources
        )
        lote.accept_row(row)
        return row

    def test_loading_keeps_only_pdfs_sorted(self):
        lote = self.make_batch()
        self.assertEqual([Path(p).name for p in lote.files], ['a.pdf', 'b.pdf', 'c.pdf'])
        self.assertEqual({lote.status(p) for p in lote.files}, {'Pendente'})
        self.assertEqual(lote.counts(), (3, 0, 0, 3))
        self.assertEqual(lote.summary_text(), '3 arquivos  |  0 prontos  |  0 para revisar  |  3 bloqueados')

    def test_adding_keeps_what_was_already_read_and_ignores_duplicates(self):
        lote = self.make_batch(('a.pdf',))
        self.analyze(lote, lote.files[0])
        lote.filter_status = 'Revisar'
        extra = make_pdf(self.tmp / 'z.pdf')
        self.assertEqual(lote.add([extra, lote.files[0]]), 1)
        self.assertEqual(len(lote.files), 2)
        self.assertEqual(lote.status(lote.files[0]), 'OK')
        self.assertEqual(lote.filter_status, 'Todos')
        self.assertEqual(lote.add([extra]), 0)

    def test_filters(self):
        lote = self.make_batch()
        a, b, c = lote.files
        self.analyze(lote, a)
        self.analyze(lote, b, conf=0.2)
        lote.set_error(c, 'quebrou')
        self.assertEqual(lote.visible_paths('Prontos'), [a])
        self.assertEqual(lote.visible_paths('Revisar'), [b])
        self.assertEqual(lote.visible_paths('Bloqueados'), [c])
        self.assertEqual(lote.visible_paths('Todos'), [a, b, c])
        self.assertEqual(lote.counts(), (3, 1, 1, 1))

    def test_row_values_show_the_table_columns(self):
        lote = self.make_batch()
        a = lote.files[0]
        self.assertEqual(lote.row_values(a), ('a.pdf', '', '', '', 'Pendente'))
        self.analyze(lote, a, conf=0.804)
        self.assertEqual(lote.row_values(a), ('a.pdf', '12345 - ANA SILVA - MARÇO 2026.PDF', 'OCR', '80%', 'OK'))
        lote.approve_as_category([a], 'Declarações')
        self.assertEqual(lote.row_values(a)[3], 'N/A')

    def test_same_named_files_show_their_folder(self):
        lote = batch.Batch()
        lote.load(
            [make_pdf(self.tmp / 'x' / 'doc.pdf'), make_pdf(self.tmp / 'y' / 'doc.pdf'), make_pdf(self.tmp / 'o.pdf')]
        )
        names = sorted(lote.display_name(p) for p in lote.files)
        self.assertEqual(names, ['doc.pdf  [x]', 'doc.pdf  [y]', 'o.pdf'])

    def test_naming_options_change_names_but_not_approved_status(self):
        lote = self.make_batch()
        a, b, c = lote.files
        self.analyze(lote, a)
        self.analyze(lote, b)
        lote.approve([b])
        lote.approve_as_category([c], 'Atestados')
        lote.set_options(True, False, False)
        lote.refresh_names()
        self.assertEqual(lote.rows[a]['new'], '12345.PDF')
        self.assertEqual(lote.rows[b]['status'], 'APROVADO')
        self.assertEqual(lote.rows[c]['status'], 'APROVADO')
        lote.set_output_format('PNG')
        lote.refresh_names()
        self.assertTrue(lote.rows[a]['new'].endswith('.PNG'))
        self.assertTrue(lote.rows[c]['new'].endswith('.PNG'))
        self.assertEqual(lote.set_output_format('xyz'), 'PDF')

    def test_only_ready_named_files_can_be_approved(self):
        lote = self.make_batch()
        a, b, c = lote.files
        self.analyze(lote, a, conf=0.3)
        lote.set_error(b, 'erro')
        self.assertEqual(lote.approve([a, b, c]), 1)  # só o REVISAR com nome
        self.assertEqual(lote.status(a), 'APROVADO')
        self.assertEqual(lote.status(b), 'ERRO')
        self.assertEqual(lote.status(c), 'Pendente')

    def test_mark_for_review_skips_blocked_files(self):
        lote = self.make_batch()
        a, b, _c = lote.files
        self.analyze(lote, a)
        lote.set_error(b, 'erro')
        self.assertEqual(lote.mark_review([a, b]), 1)
        self.assertEqual((lote.status(a), lote.status(b)), ('REVISAR', 'ERRO'))

    def test_manual_correction_sets_a_clean_name_and_status(self):
        lote = self.make_batch()
        a = lote.files[0]
        row = lote.correct(a, {'chapa': '999', 'nome': 'JOÃO/DA:SILVA', 'mes': 'ABRIL'})
        self.assertEqual((row['status'], row['method'], row['chapa_source']), ('CORRIGIDO', 'Manual', 'manual'))
        self.assertEqual(row['new'], '999 - JOÃO DA SILVA - ABRIL.PDF')
        self.assertEqual(lote.counts()[1], 1)

    def test_removing_forgets_everything_about_the_file(self):
        lote = self.make_batch()
        a, b, _c = lote.files
        self.analyze(lote, a)
        self.assertEqual(lote.remove([a, 'nao-esta-no-lote']), [a])
        self.assertNotIn(a, lote.files)
        self.assertNotIn(a, lote.rows)
        self.assertNotIn(a, lote.original_sources)
        self.assertIn(b, lote.files)

    def test_analysis_snapshot_can_be_restored(self):
        lote = self.make_batch()
        a, b, _c = lote.files
        self.analyze(lote, a)
        snapshot = lote.begin_analysis([b], selected_only=True)
        self.assertIn(a, lote.rows)  # os não selecionados continuam
        snapshot = lote.begin_analysis([], selected_only=False)
        self.assertEqual(lote.rows, {})
        self.analyze(lote, b)
        lote.restore_snapshot(snapshot)
        self.assertEqual(list(lote.rows), [a])
        self.assertEqual(lote.pending(lote.files), [b, lote.files[2]])


class SessionTests(TempCase):
    def test_a_session_round_trips(self):
        lote = batch.Batch()
        lote.load([make_pdf(self.tmp / 'a.pdf'), make_pdf(self.tmp / 'b.pdf')])
        a = lote.files[0]
        lote.accept_row(batch.row_from_result(a, timesheet_result(), lote.options, 'PDF', {}))
        lote.set_options(True, False, True)
        lote.set_output_format('PNG')
        lote.filter_status = 'Prontos'
        self.assertTrue(lote.save_session())
        data = batch.read_session_file()
        again = batch.Batch()
        self.assertEqual(again.restore_session(data, [p for p in data['files'] if Path(p).is_file()]), 2)
        self.assertEqual(again.options, (True, False, True))
        self.assertEqual((again.output_format, again.filter_status), ('PNG', 'Prontos'))
        self.assertEqual(again.status(a), 'OK')
        self.assertEqual(again.status(again.files[1]), 'Pendente')

    def test_the_session_is_saved_even_if_the_data_folder_was_deleted(self):
        """Regressão: com a pasta de dados apagada (limpeza do Windows, antivírus), salvar a sessão falhava calado."""
        import shutil

        lote = batch.Batch()
        lote.load([make_pdf(self.tmp / 'a.pdf')])
        lote.accept_row(batch.row_from_result(lote.files[0], timesheet_result(), lote.options, 'PDF', {}))
        shutil.rmtree(config.SESSION_FILE.parent)
        self.assertTrue(lote.save_session())
        self.assertTrue(config.SESSION_FILE.exists())

    def test_old_sessions_with_unknown_chapa_origin_go_back_to_review(self):
        pdf = make_pdf(self.tmp / 'a.pdf')
        data = {'files': [pdf], 'rows': [{'path': pdf, 'status': 'OK', 'chapa_source': 'desconhecida'}]}
        lote = batch.Batch()
        lote.restore_session(data, [pdf])
        self.assertEqual(lote.status(pdf), 'REVISAR')

    def test_saving_can_be_disabled_and_the_file_discarded(self):
        lote = batch.Batch()
        lote.load([make_pdf(self.tmp / 'a.pdf')])
        self.assertTrue(lote.save_session())
        lote.persistence_disabled = True
        config.SESSION_FILE.unlink()
        self.assertFalse(lote.save_session())
        self.assertFalse(config.SESSION_FILE.exists())
        self.assertIsNone(batch.read_session_file())
        config.SESSION_FILE.write_text('{', encoding='utf-8')
        with self.assertRaises(ValueError):
            batch.read_session_file()
        batch.Batch.discard_session_file()
        self.assertFalse(config.SESSION_FILE.exists())


class InputTests(TempCase):
    def test_folders_become_their_supported_files(self):
        folder = self.tmp / 'pasta'
        make_pdf(folder / 'a.pdf')
        Image.new('RGB', (10, 10)).save(folder / 'b.png')
        (folder / 'c.txt').write_text('x')
        names = [p.name for p in inputs.candidates_from([folder, self.tmp / 'solto.PDF', self.tmp / 'nada.doc'])]
        self.assertEqual(names, ['a.pdf', 'b.png', 'solto.PDF'])

    def test_limits(self):
        files = [make_pdf(self.tmp / f'{n}.pdf') for n in range(3)]
        with mock.patch.object(config, 'MAX_BATCH_FILES', 2):
            check = inputs.check_batch_limits([], files)
        self.assertEqual(check.incoming, [])
        self.assertEqual(check.error[0], 'Limite do lote')
        with mock.patch.object(config, 'MAX_BATCH_PAGES', 2):
            self.assertEqual(inputs.check_batch_limits([], files).error[0], 'Limite de páginas')
        with mock.patch.object(config, 'MAX_FILE_SIZE_MB', 0):
            self.assertEqual(inputs.check_batch_limits([], files).error[0], 'Arquivo acima do limite')
        with mock.patch.object(config, 'LARGE_FILE_WARNING_MB', 0):
            check = inputs.check_batch_limits([], files)
        self.assertEqual((len(check.incoming), len(check.large), check.error), (3, 3, None))
        self.assertIn('Deseja continuar?', inputs.large_files_message(check.large))

    def test_files_already_in_the_batch_are_not_counted_twice(self):
        a = make_pdf(self.tmp / 'a.pdf')
        check = inputs.check_batch_limits([a], [a, make_pdf(self.tmp / 'b.pdf')])
        self.assertEqual([Path(p).name for p in check.incoming], ['b.pdf'])

    def test_splitting_creates_one_pdf_per_page_in_the_app_folder(self):
        pdf = make_pdf(self.tmp / 'tres.pdf', pages=3)
        pages = inputs.split_pdf_pages(pdf)
        self.assertEqual(len(pages), 3)
        for number, page in enumerate(pages, start=1):
            self.assertEqual(Path(page).parent, self.split_dir)
            self.assertIn(f'pagina_{number:03d}', page)
            self.assertEqual(inputs.pdf_page_total(page), 1)

    def test_images_become_pdfs_and_keep_their_original(self):
        image = self.tmp / 'foto.png'
        Image.new('RGB', (200, 300), 'white').save(image)
        internal, original, generated = inputs.normalize_input_file(image)
        self.assertTrue(generated)
        self.assertEqual((Path(internal).parent, original), (self.convert_dir, str(image)))
        self.assertEqual(inputs.pdf_page_total(internal), 1)
        pdf = make_pdf(self.tmp / 'a.pdf')
        self.assertEqual(inputs.normalize_input_file(pdf), (pdf, pdf, False))

    def test_fake_files_are_rejected(self):
        fake = self.tmp / 'falso.pdf'
        fake.write_bytes(b'nao sou pdf')
        with self.assertRaises(ValueError):
            inputs.normalize_input_file(fake)

    def test_only_temporary_files_made_by_the_app_are_deleted(self):
        own = self.split_dir / 'x.pdf'
        own.write_bytes(b'x')
        users = Path(make_pdf(self.tmp / 'meu.pdf'))
        handled = inputs.cleanup_generated_files([str(own), str(users)])
        self.assertEqual(handled, [str(own)])
        self.assertFalse(own.exists())
        self.assertTrue(users.exists())


class AnalysisRunnerTests(unittest.TestCase):
    def collect(self, files, analyze, cancel=None, discard=None, workers=2, build=None):
        events = []
        done = analysis_runner.run_analysis(
            files,
            {},
            build or (lambda path, result: {'path': path, **result}),
            lambda *e: events.append(e),
            cancel or threading.Event(),
            discard,
            analyze=analyze,
            workers=workers,
        )
        return events, done

    def test_every_file_reports_a_result_and_progress_and_finishes_last(self):
        events, done = self.collect(['a', 'b', 'c'], lambda path, page: {'value': path.upper()})
        self.assertEqual(done, 3)
        kinds = [kind for kind, _data in events]
        self.assertEqual(kinds[-1], 'finished')
        self.assertEqual(kinds.count('result'), 3)
        self.assertEqual(sorted(data['path'] for kind, data in events if kind == 'result'), ['a', 'b', 'c'])
        progress = [data for kind, data in events if kind == 'progress']
        self.assertEqual([p[0] for p in progress], [1, 2, 3])
        self.assertTrue(all(p[1] == 3 for p in progress))

    def test_a_failing_file_becomes_an_error_and_the_others_continue(self):
        def analyze(path, page):
            if path == 'ruim':
                raise RuntimeError('quebrou')
            return {'value': 1}

        events, done = self.collect(['ok', 'ruim', 'ok2'], analyze)
        errors = [data for kind, data in events if kind == 'error']
        self.assertEqual(done, 3)
        self.assertEqual([(path, str(exc)) for path, exc in errors], [('ruim', 'quebrou')])
        self.assertEqual(sum(1 for kind, _d in events if kind == 'result'), 2)

    def test_cancelling_stops_new_files_from_starting(self):
        cancel = threading.Event()
        started = []

        def analyze(path, page):
            started.append(path)
            cancel.set()  # o primeiro arquivo pede o cancelamento
            return {'value': 1}

        _events, done = self.collect([str(n) for n in range(10)], analyze, cancel=cancel, workers=1)
        self.assertEqual(started, ['0'])
        self.assertEqual(done, 1)

    def test_discarding_hides_results_but_still_finishes(self):
        discard = threading.Event()
        discard.set()
        events, _done = self.collect(['a', 'b'], lambda path, page: {'value': 1}, discard=discard)
        self.assertEqual([kind for kind, _d in events if kind in ('result', 'error')], [])
        self.assertEqual(events[-1][0], 'finished')

    def test_a_broken_row_builder_is_reported_as_an_error(self):
        def build(path, result):
            raise ValueError('linha inválida')

        events, _done = self.collect(['a'], lambda path, page: {}, build=build)
        self.assertEqual([kind for kind, _d in events], ['error', 'progress', 'finished'])


class ExportTests(TempCase):
    def make_ready_batch(self, count=2):
        lote = batch.Batch()
        lote.load([make_pdf(self.tmp / 'orig' / f'{n}.pdf', pages=2, text=f'doc{n}') for n in range(count)])
        for index, path in enumerate(lote.files):
            result = timesheet_result(chapa=str(100 + index), nome='ANA', mes='MARÇO')
            lote.accept_row(batch.row_from_result(path, result, lote.options, 'PDF', {}))
        return lote

    def test_nothing_blocks_a_ready_batch(self):
        lote = self.make_ready_batch()
        self.assertEqual(exporter.export_problems(lote), [])

    def test_problems_explain_why_a_file_cannot_be_exported(self):
        lote = self.make_ready_batch(4)
        a, b, c, d = lote.files
        lote.rows.pop(a)  # pendente
        lote.set_error(b, 'erro')
        lote.rows[c]['status'] = 'NAO RECONHECIDO'
        lote.rows[d]['new'] = '   '
        reasons = dict(exporter.export_problems(lote))
        self.assertEqual(reasons[a], 'análise ainda não realizada')
        self.assertEqual(reasons[b], 'erro durante a leitura do PDF')
        self.assertEqual(reasons[c], 'matrícula ou nome não reconhecido')
        self.assertEqual(reasons[d], 'novo nome está vazio')
        Path(a).unlink()
        lote.rows[a] = {'path': a, 'status': 'OK', 'new': 'X.PDF'}
        self.assertEqual(dict(exporter.export_problems(lote, [a]))[a], 'arquivo original não foi encontrado')

    def test_pdfs_are_copied_with_the_new_name(self):
        lote = self.make_ready_batch()
        out = self.tmp / 'saida'
        out.mkdir()
        result = exporter.export_batch(lote, out)
        self.assertEqual((result.count, result.failures), (2, []))
        self.assertEqual(sorted(p.name for p in out.iterdir()), ['100 - ANA - MARÇO.PDF', '101 - ANA - MARÇO.PDF'])
        with fitz.open(out / '100 - ANA - MARÇO.PDF') as copy:
            self.assertEqual(copy.page_count, 2)

    def test_existing_files_are_never_overwritten(self):
        lote = self.make_ready_batch(1)
        out = self.tmp / 'saida'
        out.mkdir()
        (out / '100 - ANA - MARÇO.PDF').write_bytes(b'do usuario')
        exporter.export_batch(lote, out)
        self.assertEqual((out / '100 - ANA - MARÇO.PDF').read_bytes(), b'do usuario')
        self.assertTrue((out / '100 - ANA - MARÇO (2).PDF').exists())

    def test_two_files_with_the_same_name_get_numbered(self):
        lote = self.make_ready_batch(2)
        for path in lote.files:
            lote.rows[path]['new'] = 'IGUAL.PDF'
        out = self.tmp / 'saida'
        out.mkdir()
        self.assertEqual(exporter.export_batch(lote, out).count, 2)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ['IGUAL (2).PDF', 'IGUAL.PDF'])

    def test_certificates_go_to_their_own_subfolder(self):
        lote = self.make_ready_batch(2)
        lote.approve_as_category([lote.files[1]], 'Atestados')
        out = self.tmp / 'saida'
        out.mkdir()
        result = exporter.export_batch(lote, out)
        self.assertEqual(result.separated, {'Atestados': 1, 'Declarações': 0})
        self.assertEqual(len(list((out / 'Atestados').iterdir())), 1)

    def test_images_get_one_file_per_page(self):
        lote = self.make_ready_batch(1)
        lote.set_output_format('PNG')
        lote.refresh_names()
        out = self.tmp / 'saida'
        out.mkdir()
        result = exporter.export_batch(lote, out)
        self.assertEqual(result.count, 2)
        self.assertEqual(
            sorted(p.name for p in out.iterdir()),
            ['100 - ANA - MARÇO - PÁGINA 001.PNG', '100 - ANA - MARÇO - PÁGINA 002.PNG'],
        )

    def test_one_failure_does_not_stop_the_others_and_is_reported(self):
        lote = self.make_ready_batch(2)
        real = exporter.export_source

        def flaky(source, target, fmt):
            if source == lote.files[0]:
                raise OSError('disco cheio')
            return real(source, target, fmt)

        out = self.tmp / 'saida'
        out.mkdir()
        with mock.patch.object(exporter, 'export_source', flaky):
            result = exporter.export_batch(lote, out)
        self.assertEqual(result.count, 1)
        self.assertEqual(result.failures, [(lote.files[0], 'disco cheio')])

    def test_review_files_are_exported_too_but_blocked_ones_are_not(self):
        lote = self.make_ready_batch(3)
        lote.rows[lote.files[0]]['status'] = 'REVISAR'
        lote.set_error(lote.files[1], 'x')
        items = [Path(p).name for p, _stem in exporter.exportable_items(lote)]
        self.assertEqual(items, ['0.pdf', '2.pdf'])


if __name__ == '__main__':
    unittest.main()

"""Planejamento e execução das ferramentas (rdf.pdftools.jobs): sem interface, só resultados reais."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import _source  # coloca a raiz do projeto no sys.path
import fitz
from rdf.pdftools import jobs, ops
from rdf.pdftools.registry import TOOLS_BY_ID, Option


def make_pdf(path, pages=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for number in range(pages):
        document.new_page().insert_text((50, 50), f'p{number}')
    document.save(path)
    document.close()
    return path


class ValueTests(unittest.TestCase):
    def test_numbers_accept_a_decimal_comma(self):
        self.assertEqual(jobs.parse_int('7', 'x'), 7)
        self.assertEqual(jobs.parse_int(' 2,9 ', 'x'), 2)
        self.assertEqual(jobs.parse_int(5, 'x'), 5)

    def test_invalid_numbers_explain_which_field(self):
        for raw in ('abc', '', 'inf', 'nan'):
            with self.subTest(raw=raw), self.assertRaises(ops.PdfToolError) as caught:
                jobs.parse_int(raw, 'Páginas por arquivo')
            self.assertIn('Páginas por arquivo', str(caught.exception))

    def test_collect_values_converts_only_numbers(self):
        options = (Option('n', 'N', 'int', 1), Option('t', 'T', 'text', ''), Option('b', 'B', 'bool', True))
        values = jobs.collect_values(options, {'n': '3', 't': 'abc', 'b': False})
        self.assertEqual(values, {'n': 3, 't': 'abc', 'b': False})

    def test_visibility_follows_the_other_option(self):
        by_value = Option('a', 'A', 'text', '', visible_if=('mode', 'Por intervalos'))
        by_set = Option('b', 'B', 'text', '', visible_if=('size', ('A4', 'Carta')))
        always = Option('c', 'C', 'text', '')
        self.assertTrue(jobs.option_visible(by_value, {'mode': 'Por intervalos'}))
        self.assertFalse(jobs.option_visible(by_value, {'mode': 'Outro'}))
        self.assertTrue(jobs.option_visible(by_set, {'size': 'Carta'}))
        self.assertFalse(jobs.option_visible(by_set, {'size': 'Ajustar'}))
        self.assertTrue(jobs.option_visible(always, {}))


class DestinationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_which_dialog_each_mode_needs(self):
        self.assertEqual(jobs.destination_kind(TOOLS_BY_ID['merge'], ['a', 'b']), 'save-as')
        self.assertEqual(jobs.destination_kind(TOOLS_BY_ID['compress'], ['a']), 'save-as')
        self.assertEqual(jobs.destination_kind(TOOLS_BY_ID['compress'], ['a', 'b']), 'folder')
        self.assertEqual(jobs.destination_kind(TOOLS_BY_ID['split'], ['a']), 'folder')

    def test_save_as_jobs(self):
        merge = jobs.jobs_for_save_as(TOOLS_BY_ID['merge'], ['a.pdf', 'b.pdf'], self.tmp / 'x.pdf')
        self.assertEqual(merge, [(['a.pdf', 'b.pdf'], self.tmp / 'x.pdf')])
        single = jobs.jobs_for_save_as(TOOLS_BY_ID['compress'], ['a.pdf'], self.tmp / 'x.pdf')
        self.assertEqual(single, [('a.pdf', self.tmp / 'x.pdf')])

    def test_same_named_files_from_different_folders_never_share_a_destination(self):
        files = [make_pdf(self.tmp / folder / 'doc.pdf') for folder in ('x', 'y', 'z')]
        out = self.tmp / 'saida'
        out.mkdir()
        planned = jobs.jobs_for_folder(TOOLS_BY_ID['compress'], files, out)
        names = [dest.name.lower() for _origin, dest in planned]
        self.assertEqual(len(set(names)), 3, names)
        self.assertEqual(names[0], 'doc_comprimido.pdf')

    def test_existing_files_are_never_overwritten(self):
        out = self.tmp / 'saida'
        out.mkdir()
        (out / 'doc_comprimido.pdf').write_bytes(b'x')
        planned = jobs.jobs_for_folder(TOOLS_BY_ID['compress'], [self.tmp / 'doc.pdf'], out)
        self.assertEqual(planned[0][1].name, 'doc_comprimido (2).pdf')

    def test_tools_that_create_many_files_get_their_own_subfolder_name(self):
        planned = jobs.jobs_for_folder(TOOLS_BY_ID['split'], [self.tmp / 'doc.pdf'], self.tmp)
        self.assertEqual(planned[0][1].name, 'doc_dividido')

    def test_inspect_reads_pages_size_and_rejects_garbage(self):
        good = make_pdf(self.tmp / 'a.pdf', pages=3)
        info = jobs.inspect_file(TOOLS_BY_ID['merge'], good)
        self.assertEqual((info['pages'], info['detail'], info['locked']), (3, '3', False))
        fake = self.tmp / 'fake.pdf'
        fake.write_bytes(b'not a pdf')
        self.assertIsNone(jobs.inspect_file(TOOLS_BY_ID['merge'], fake))
        self.assertIsNone(jobs.inspect_file(TOOLS_BY_ID['merge'], self.tmp / 'missing.pdf'))


class RunTests(unittest.TestCase):
    def fake_tool(self, behavior):
        return SimpleNamespace(id='fake', run=behavior)

    def test_a_failure_does_not_stop_the_next_jobs(self):
        def behavior(source, dest, values, progress):
            progress(0.5, 'metade')
            if source == 'ruim':
                raise ops.PdfToolError('arquivo ruim')
            if source == 'estranho':
                raise RuntimeError('boom')
            return ops.Result([Path(dest)], f'ok {source}')

        reports = []
        paths, messages, failures, total = jobs.run_jobs(
            self.fake_tool(behavior),
            [('a', Path('A')), ('ruim', Path('B')), ('estranho', Path('C')), ('d', Path('D'))],
            {},
            lambda fraction, text='': reports.append(fraction),
        )
        self.assertEqual((paths, messages, total), ([Path('A'), Path('D')], ['ok a', 'ok d'], 4))
        self.assertEqual([name for name, _why in failures], ['ruim', 'estranho'])
        self.assertIn('erro inesperado', failures[1][1])
        self.assertEqual(reports, sorted(reports))  # o andamento nunca anda para trás
        self.assertAlmostEqual(reports[-1], 1.0)

    def test_a_merge_job_names_its_first_file_on_failure(self):
        def behavior(source, dest, values, progress):
            raise ops.PdfToolError('falhou')

        _paths, _messages, failures, _total = jobs.run_jobs(
            self.fake_tool(behavior), [(['um.pdf', 'dois.pdf'], Path('x.pdf'))], {}, lambda *a: None
        )
        self.assertEqual(failures, [('um.pdf', 'falhou')])


class CancelTests(unittest.TestCase):
    def test_cancelling_stops_the_running_job_and_skips_the_next_ones(self):
        started, flag = [], {'stop': False}

        def behavior(source, dest, values, progress):
            started.append(source)
            progress(0.1, 'começou')
            flag['stop'] = True  # o usuário cancela no meio do primeiro trabalho
            progress(0.5, 'metade')  # aqui a operação é interrompida
            return ops.Result([Path(dest)], 'não deveria chegar aqui')

        tool = SimpleNamespace(id='fake', run=behavior)
        paths, messages, failures, total = jobs.run_jobs(
            tool, [('a', Path('A')), ('b', Path('B'))], {}, lambda *a: None, cancelled=lambda: flag['stop']
        )
        self.assertEqual((paths, messages, failures, total), ([], [], [], 2))
        self.assertEqual(started, ['a'])  # o segundo trabalho nem começou

    def test_a_cancel_after_a_finished_job_keeps_its_result(self):
        flag = {'stop': False}

        def behavior(source, dest, values, progress):
            progress(1.0, '')
            flag['stop'] = True
            return ops.Result([Path(dest)], f'ok {source}')

        paths, _messages, failures, _total = jobs.run_jobs(
            SimpleNamespace(id='fake', run=behavior),
            [('a', Path('A')), ('b', Path('B'))],
            {},
            lambda *a: None,
            cancelled=lambda: flag['stop'],
        )
        self.assertEqual((paths, failures), ([Path('A')], []))


class SummaryTests(unittest.TestCase):
    def test_nothing_generated_shows_the_reason(self):
        single = jobs.summarize([], [], [('a.pdf', 'senha incorreta')], 1)
        self.assertFalse(single.ok)
        self.assertEqual(single.text, 'senha incorreta')
        self.assertEqual(jobs.summarize([], [], [], 1).text, 'Nada foi gerado.')
        mixed = jobs.summarize([], [], [('a', 'x'), ('b', 'y')], 2)
        self.assertEqual(mixed.text, 'a: x; b: y')

    def test_one_result_points_to_the_file(self):
        summary = jobs.summarize([Path('C:/out/a.pdf')], ['pronto'], [], 1)
        self.assertTrue(summary.ok)
        self.assertEqual(summary.output_file, Path('C:/out/a.pdf'))
        self.assertIn('pronto', summary.text)
        self.assertIn('Salvo em:', summary.text)

    def test_many_results_point_to_their_common_folder_and_report_failures(self):
        paths = [Path('C:/out/p/a.pdf'), Path('C:/out/p/b.pdf')]
        summary = jobs.summarize(paths, ['1', '2'], [('c.pdf', 'corrompido')], 3)
        self.assertIsNone(summary.output_file)
        self.assertEqual(summary.output_folder, Path('C:/out/p'))
        self.assertIn('2 de 3 arquivos processados', summary.text)
        self.assertIn('c.pdf (corrompido)', summary.text)


if __name__ == '__main__':
    unittest.main()

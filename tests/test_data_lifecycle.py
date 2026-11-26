"""Dados pessoais não ficam para trás (varredura, validade da sessão, desinstalador) e a contagem de páginas é guardada."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import _source  # coloca a raiz do projeto no sys.path
import fitz
from rdf.core import batch, config, exporter, inputs
from rdf.pdftools import ops

ROOT = _source.ROOT


def make_pdf(path, pages=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for _ in range(pages):
        document.new_page()
    document.save(path)
    document.close()
    return str(path)


class SweepTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.split, self.convert = self.tmp / 'split', self.tmp / 'convert'
        self.session = self.tmp / 'sessao.json'
        for name, value in (('SPLIT_DIR', self.split), ('CONVERT_DIR', self.convert), ('SESSION_FILE', self.session)):
            patcher = mock.patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.split.mkdir()
        self.convert.mkdir()

    def write_session(self, generated, age_days=0):
        self.session.write_text(json.dumps({'generated_files': [str(p) for p in generated]}), encoding='utf-8')
        old = time.time() - age_days * 86400
        os.utime(self.session, (old, old))

    def test_orphans_are_removed_and_files_of_a_live_session_are_kept(self):
        kept, orphan = self.split / 'a.pdf', self.convert / 'b.pdf'
        kept.write_bytes(b'x')
        orphan.write_bytes(b'x')
        self.write_session([kept])
        config.sweep_stale_data()
        self.assertTrue(kept.exists())
        self.assertFalse(orphan.exists())
        self.assertTrue(self.session.exists())

    def test_old_tool_folders_are_removed_but_recent_ones_may_be_in_use(self):
        old = self.convert / 'ferramentas' / 'abc12345' / 'x.pdf'
        recent = self.convert / 'ferramentas' / 'def67890' / 'y.pdf'
        for path in (old, recent):
            path.parent.mkdir(parents=True)
            path.write_bytes(b'x')
        past = time.time() - config.TEMP_FOLDER_MAX_AGE_SECONDS - 60
        for path in (old, old.parent):
            os.utime(path, (past, past))
        config.sweep_stale_data()
        self.assertFalse(old.parent.exists())
        self.assertTrue(recent.exists())

    def test_an_expired_session_is_discarded_with_its_copies(self):
        copy = self.split / 'a.pdf'
        copy.write_bytes(b'x')
        self.write_session([copy], age_days=config.SESSION_MAX_AGE_DAYS + 1)
        config.sweep_stale_data()
        self.assertFalse(self.session.exists())
        self.assertFalse(copy.exists())

    def test_a_damaged_session_is_discarded_instead_of_blocking_the_start(self):
        self.session.write_text('{ quebrado', encoding='utf-8')
        (self.split / 'a.pdf').write_bytes(b'x')
        config.sweep_stale_data()
        self.assertFalse(self.session.exists())
        self.assertFalse((self.split / 'a.pdf').exists())

    def test_nothing_to_sweep_is_fine(self):
        self.assertEqual(config.sweep_stale_data(), 0)


class InstallerTests(unittest.TestCase):
    def test_uninstall_deletes_the_app_data_folder(self):
        iss = (ROOT / 'packaging' / 'installer.iss').read_text(encoding='utf-8')
        self.assertIn('[UninstallDelete]', iss)
        self.assertIn(r'Name: "{localappdata}\RDF"', iss)
        self.assertEqual(config.APP_DATA_DIR.name, 'RDF')  # a pasta apagada é a mesma que o app usa


class PageCountCacheTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pdf = make_pdf(Path(tmp.name) / 'a.pdf', pages=3)

    def test_pdf_info_opens_the_file_once_until_it_changes(self):
        ops._INFO_CACHE.clear()
        with mock.patch.object(ops.fitz, 'open', wraps=fitz.open) as opened:
            self.assertEqual(ops.pdf_info(self.pdf), (3, False))
            self.assertEqual(ops.pdf_info(self.pdf), (3, False))
            self.assertEqual(opened.call_count, 1)
            make_pdf(self.pdf, pages=5)
            self.assertEqual(ops.pdf_info(self.pdf), (5, False))

    def test_pdf_info_of_a_missing_file_is_still_zero(self):
        self.assertEqual(ops.pdf_info(self.pdf + '.nao'), (0, False))

    def test_input_page_count_opens_the_file_once_until_it_changes(self):
        inputs._PAGE_COUNTS.clear()
        with mock.patch.object(inputs.fitz, 'open', wraps=fitz.open) as opened:
            self.assertEqual(inputs.input_page_count(self.pdf), 3)
            self.assertEqual(inputs.input_page_count(self.pdf), 3)
            self.assertEqual(opened.call_count, 1)
            make_pdf(self.pdf, pages=2)
            self.assertEqual(inputs.input_page_count(self.pdf), 2)


class ExportProgressTests(unittest.TestCase):
    def test_export_reports_each_file_before_exporting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            lote = batch.Batch()
            files = [make_pdf(tmp / f'in{n}.pdf') for n in range(3)]
            lote.load(files)
            for n, path in enumerate(files):
                lote.rows[path] = {'path': path, 'status': 'OK', 'new': f'N{n}.PDF'}
            seen = []
            result = exporter.export_batch(lote, tmp / 'out', progress=lambda done, total: seen.append((done, total)))
            self.assertEqual(result.count, 3)
            self.assertEqual(seen, [(0, 3), (1, 3), (2, 3)])


if __name__ == '__main__':
    unittest.main()

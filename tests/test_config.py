import logging
import os
import subprocess
import sys
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest import mock

from _source import ROOT
import pytesseract
from rdf.core import config


class ImportSideEffectTests(unittest.TestCase):
    def test_importing_the_app_creates_nothing(self):
        """Importar o aplicativo não cria pastas, log nem configura o Tesseract."""
        with tempfile.TemporaryDirectory() as data_dir:
            env = dict(os.environ, LOCALAPPDATA=data_dir)
            code = 'import rdf.__main__, rdf.qt.window, pytesseract; print(pytesseract.pytesseract.tesseract_cmd)'
            result = subprocess.run(
                [sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'tesseract')
            self.assertEqual(list(Path(data_dir).iterdir()), [])

    def test_opencv_uses_one_thread_per_worker(self):
        code = 'import rdf.qt.window, rdf.core.ocr, cv2; print(cv2.getNumThreads())'
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '1')


class LimitsTests(unittest.TestCase):
    def test_batch_limits(self):
        self.assertEqual(config.MAX_BATCH_FILES, 300)
        self.assertEqual(config.MAX_BATCH_PAGES, 1000)
        self.assertEqual(config.MAX_FILE_SIZE_MB, 100)
        self.assertEqual(config.LARGE_FILE_WARNING_MB, 30)
        self.assertEqual(config.PARALLEL_WORKERS, 4)

    def test_output_formats(self):
        self.assertEqual(config.OUTPUT_FORMATS, ('PDF', 'PNG', 'JPEG', 'JPG', 'WEBP', 'BMP', 'TIFF'))

    def test_app_data_folder_keeps_internal_name(self):
        self.assertEqual(config.APP_DATA_DIR.name, 'RDF')
        for path in (config.LOG_DIR, config.SESSION_FILE, config.SPLIT_DIR, config.CONVERT_DIR):
            self.assertTrue(path.is_relative_to(config.APP_DATA_DIR))


class SetupTests(unittest.TestCase):
    def test_ensure_app_dirs_creates_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            wanted = [Path(tmp) / 'logs', Path(tmp) / 'a' / 'b']
            config.ensure_app_dirs(wanted)
            self.assertTrue(all(path.is_dir() for path in wanted))

    def test_log_rotation_is_bounded_and_added_once(self):
        logger = logging.getLogger('rdf-test-setup-logging')
        with tempfile.TemporaryDirectory() as tmp:
            try:
                config.setup_logging(tmp, logger)
                config.setup_logging(tmp, logger)
                self.assertEqual(len(logger.handlers), 1)
                handler = logger.handlers[0]
                self.assertIsInstance(handler, RotatingFileHandler)
                self.assertEqual(handler.maxBytes, 2 * 1024 * 1024)
                self.assertEqual(handler.backupCount, 3)
                self.assertFalse(logger.propagate)
                logger.info('linha de teste')
                handler.flush()
                self.assertIn('linha de teste', (Path(tmp) / 'renomeador.log').read_text(encoding='utf-8'))
            finally:
                for handler in list(logger.handlers):
                    handler.close()
                    logger.removeHandler(handler)


class TesseractTests(unittest.TestCase):
    def setUp(self):
        self.previous_cmd = pytesseract.pytesseract.tesseract_cmd
        self.env = mock.patch.dict(os.environ)
        self.env.start()

    def tearDown(self):
        pytesseract.pytesseract.tesseract_cmd = self.previous_cmd
        self.env.stop()

    def test_bundled_tesseract_is_preferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'Tesseract-OCR' / 'tesseract.exe'
            (exe.parent / 'tessdata').mkdir(parents=True)
            exe.write_bytes(b'')
            self.assertEqual(config.configure_tesseract(tmp), str(exe))
            self.assertEqual(pytesseract.pytesseract.tesseract_cmd, str(exe))
            self.assertEqual(os.environ['TESSDATA_PREFIX'], str(exe.parent / 'tessdata'))

    def test_manual_path_file_is_used_when_nothing_is_bundled(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'outro lugar' / 'tesseract.exe'
            exe.parent.mkdir()
            exe.write_bytes(b'')
            (Path(tmp) / 'tesseract_path.txt').write_text(str(exe), encoding='utf-8-sig')
            self.assertEqual(config.configure_tesseract(tmp), str(exe))

    def test_candidates_start_with_bundle_then_manual_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'tesseract_path.txt').write_text('C:/manual/tesseract.exe', encoding='utf-8')
            candidates = config.tesseract_candidates(tmp)
            self.assertEqual(candidates[0], os.path.join(tmp, 'Tesseract-OCR', 'tesseract.exe'))
            self.assertEqual(candidates[1], 'C:/manual/tesseract.exe')


if __name__ == '__main__':
    unittest.main()

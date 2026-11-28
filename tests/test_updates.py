"""Atualização pelo GitHub (rdf/core/updates.py), sem internet: um "GitHub" falso responde no lugar do de verdade."""

import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

import _source  # coloca a raiz do projeto no sys.path
from rdf.core import updates

INSTALLER = b'MZ' + b'instalador do RDF ' * 5000
SETUP_URL = 'https://github.com/zac098/prototype/releases/download/v9.1.0/RDF_Setup_9.1.0.exe'
SUMS_URL = 'https://github.com/zac098/prototype/releases/download/v9.1.0/SHA256SUMS.txt'


def release_json(tag='v9.1.0', **extra):
    data = {
        'tag_name': tag,
        'html_url': 'https://github.com/zac098/prototype/releases/tag/' + tag,
        'body': '## 9.1.0\n- Novidade',
        'draft': False,
        'prerelease': False,
        'assets': [
            {
                'name': 'RDF_portatil_9.1.0.exe',
                'browser_download_url': SETUP_URL.replace('Setup', 'portatil'),
                'size': 10,
            },
            {'name': 'RDF_Setup_9.1.0.exe', 'browser_download_url': SETUP_URL, 'size': len(INSTALLER)},
            {'name': 'SHA256SUMS.txt', 'browser_download_url': SUMS_URL, 'size': 200},
        ],
    }
    data.update(extra)
    return data


class FakeResponse(io.BytesIO):
    def __init__(self, data, length=True):
        super().__init__(data)
        self.headers = {'Content-Length': str(len(data))} if length else {}


class FakeGitHub:
    """Responde por URL; guarda os pedidos para conferir cabeçalhos."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        answer = self.routes.get(request.full_url)
        if answer is None:
            raise urllib.error.HTTPError(request.full_url, 404, 'Not Found', {}, None)
        if isinstance(answer, Exception):
            raise answer
        return answer() if callable(answer) else FakeResponse(answer)


def sums_text(data=INSTALLER, name='RDF_Setup_9.1.0.exe'):
    return f'{hashlib.sha256(data).hexdigest()}  {name}\r\n{"0" * 64}  RDF_portatil_9.1.0.exe\r\n'.encode()


class VersionTests(unittest.TestCase):
    def test_versions_are_compared_as_numbers(self):
        self.assertTrue(updates.is_newer('4.1.0', '4.0.2'))
        self.assertTrue(updates.is_newer('v4.10.0', '4.9.9'))  # 10 > 9, não "1" < "9"
        self.assertFalse(updates.is_newer('4.0.2', '4.0.2'))
        self.assertFalse(updates.is_newer('4.1', '4.1.0'))
        self.assertFalse(updates.is_newer('4.0.1', '4.0.2'))
        self.assertFalse(updates.is_newer('lixo', '4.0.2'))
        self.assertEqual(updates.parse_version('v4.1.0'), (4, 1, 0))
        self.assertIsNone(updates.parse_version('4.1.0-beta'))


class ReleaseParsingTests(unittest.TestCase):
    def test_the_installer_and_the_checksums_are_found(self):
        release = updates.parse_release(release_json())
        self.assertEqual(release.version, '9.1.0')
        self.assertEqual(release.installer_url, SETUP_URL)
        self.assertEqual(release.installer_name, 'RDF_Setup_9.1.0.exe')
        self.assertEqual(release.installer_size, len(INSTALLER))
        self.assertEqual(release.checksums_url, SUMS_URL)
        self.assertTrue(release.can_install)
        self.assertIn('Novidade', release.notes)

    def test_drafts_prereleases_and_odd_answers_are_ignored(self):
        self.assertIsNone(updates.parse_release(release_json(draft=True)))
        self.assertIsNone(updates.parse_release(release_json(prerelease=True)))
        self.assertIsNone(updates.parse_release(release_json(tag='teste')))
        self.assertIsNone(updates.parse_release(['não', 'é', 'uma', 'release']))

    def test_links_that_are_not_https_are_not_used(self):
        data = release_json()
        data['assets'][1]['browser_download_url'] = 'http://exemplo.com/RDF_Setup_9.1.0.exe'
        data['html_url'] = 'javascript:alert(1)'
        release = updates.parse_release(data)
        self.assertFalse(release.can_install)
        self.assertEqual(release.page_url, updates.RELEASES_PAGE)


class NotesTests(unittest.TestCase):
    def test_the_install_instructions_of_the_release_page_stay_out_of_the_app(self):
        body = (
            '**Como instalar:** baixe o `RDF_Setup_9.1.0.exe` abaixo e execute.\r\n'
            'O `RDF_portatil_9.1.0.exe` roda sem instalar.\r\n\r\n## 9.1.0\r\n- Abre mais rápido\r\n'
        )
        self.assertEqual(updates.notes_for_app(body), '## 9.1.0\n- Abre mais rápido')
        self.assertEqual(updates.notes_for_app(None), '')


class CheckTests(unittest.TestCase):
    def test_a_newer_version_is_reported(self):
        github = FakeGitHub({updates.LATEST_API: json.dumps(release_json()).encode()})
        release = updates.check('4.0.2', opener=github)
        self.assertEqual(release.version, '9.1.0')
        request, timeout = github.requests[0]
        self.assertEqual(request.get_header('User-agent'), updates.USER_AGENT)  # só "RDF/versão", nada do usuário
        self.assertEqual(timeout, updates.TIMEOUT_SECONDS)

    def test_the_same_or_an_older_version_is_not_an_update(self):
        github = FakeGitHub({updates.LATEST_API: json.dumps(release_json('v4.0.2')).encode()})
        self.assertIsNone(updates.check('4.0.2', opener=github))
        self.assertIsNone(updates.check('9.9.9', opener=github))

    def test_network_problems_become_a_clear_message(self):
        for problem in (urllib.error.URLError('sem rede'), TimeoutError('tempo esgotado')):
            github = FakeGitHub({updates.LATEST_API: problem})
            with self.subTest(problem=problem), self.assertRaisesRegex(updates.UpdateError, 'GitHub'):
                updates.check('4.0.2', opener=github)
        with self.assertRaisesRegex(updates.UpdateError, 'HTTP 404'):
            updates.check('4.0.2', opener=FakeGitHub({}))
        with self.assertRaises(updates.UpdateError):
            updates.check('4.0.2', opener=FakeGitHub({updates.LATEST_API: b'<html>erro</html>'}))


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.release = updates.parse_release(release_json())

    def test_the_installer_is_downloaded_and_verified(self):
        github = FakeGitHub({SETUP_URL: INSTALLER, SUMS_URL: sums_text()})
        seen = []
        path = updates.download_installer(
            self.release, self.folder, progress=lambda done, total: seen.append((done, total)), opener=github
        )
        self.assertEqual(path.read_bytes(), INSTALLER)
        self.assertEqual(seen[-1], (len(INSTALLER), len(INSTALLER)))
        self.assertEqual([p.name for p in self.folder.iterdir()], ['RDF_Setup_9.1.0.exe'])  # sem .parcial

    def test_a_corrupted_download_is_deleted(self):
        github = FakeGitHub({SETUP_URL: INSTALLER, SUMS_URL: sums_text(b'outro arquivo')})
        with self.assertRaisesRegex(updates.UpdateError, 'corrompido'):
            updates.download_installer(self.release, self.folder, opener=github)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_without_a_published_checksum_nothing_is_downloaded(self):
        github = FakeGitHub({SETUP_URL: INSTALLER, SUMS_URL: b'nada aqui'})
        with self.assertRaisesRegex(updates.UpdateError, 'soma de verificação'):
            updates.download_installer(self.release, self.folder, opener=github)
        self.assertEqual([request.full_url for request, _ in github.requests], [SUMS_URL])

    def test_an_interrupted_download_leaves_nothing_behind(self):
        github = FakeGitHub({SETUP_URL: self.short_response, SUMS_URL: sums_text()})
        with self.assertRaisesRegex(updates.UpdateError, 'incompleto'):
            updates.download_installer(self.release, self.folder, opener=github)
        self.assertEqual(list(self.folder.iterdir()), [])

    def short_response(self):
        response = FakeResponse(INSTALLER[:1000])
        response.headers = {'Content-Length': str(len(INSTALLER))}  # prometeu mais do que entregou
        return response

    def test_cancel_stops_the_download(self):
        github = FakeGitHub({SETUP_URL: INSTALLER, SUMS_URL: sums_text()})
        with self.assertRaises(updates.Cancelled):
            updates.download_installer(self.release, self.folder, cancelled=lambda: True, opener=github)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_checksum_files_in_sha256sum_format(self):
        sums = updates.parse_checksums('ABC\n' + 'a' * 64 + '  RDF_Setup_1.exe\n' + 'b' * 64 + ' *RDF_portatil_1.exe')
        self.assertEqual(sums, {'RDF_Setup_1.exe': 'a' * 64, 'RDF_portatil_1.exe': 'b' * 64})


class InstallTests(unittest.TestCase):
    def test_only_the_installed_copy_updates_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'RDF.exe'
            exe.write_bytes(b'MZ')
            self.assertFalse(updates.is_installed_copy(exe))  # portátil: abre a página da versão
            (Path(tmp) / 'unins000.exe').write_bytes(b'MZ')
            self.assertTrue(updates.is_installed_copy(exe))
        self.assertFalse(updates.is_installed_copy())  # rodando do código-fonte

    def test_the_installer_runs_silently_and_closes_the_app(self):
        command = updates.installer_command(Path('C:/temp/RDF_Setup_9.1.0.exe'))
        self.assertTrue(command[0].endswith('RDF_Setup_9.1.0.exe'))
        self.assertIn('/SILENT', command)
        self.assertIn('/CLOSEAPPLICATIONS', command)
        self.assertNotIn('/VERYSILENT', command)  # a barra de progresso aparece: o usuário vê que está instalando

    def test_the_installer_reopens_the_app_after_a_silent_update(self):
        iss = (_source.ROOT / 'packaging' / 'installer.iss').read_text(encoding='utf-8')
        self.assertIn('Check: WizardSilent', iss)


if __name__ == '__main__':
    unittest.main()

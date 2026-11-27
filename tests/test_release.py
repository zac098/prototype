"""Consistência da versão, do instalador e do histórico."""

import unittest

from _source import ROOT
from rdf import APP_VERSION

ISS = (ROOT / 'packaging' / 'installer.iss').read_text(encoding='utf-8')


class ReleaseTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, '4.0.0')

    def test_installer_matches_the_app(self):
        self.assertIn(f'#define MyAppVersion "{APP_VERSION}"', ISS)
        self.assertIn('#define MyAppName "Renomeador de Folhas (RDF)"', ISS)
        self.assertIn('#define MyAppExeName "RDF.exe"', ISS)

    def test_readme_is_not_a_prototype(self):
        self.assertNotIn('prototype.1', (ROOT / 'docs' / 'LEIA-ME.txt').read_text(encoding='utf-8'))

    def test_history_keeps_real_versions(self):
        history = (ROOT / 'docs' / 'CHANGELOG.md').read_text(encoding='utf-8')
        for version in ('1.7.7', '1.7.8', '1.7.9', '1.8.0', '1.8.1', '1.8.2', '1.8.3', '2.0.4', '2.1.0', APP_VERSION):
            self.assertIn(version, history)


if __name__ == '__main__':
    unittest.main()

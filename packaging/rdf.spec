# -*- mode: python ; coding: utf-8 -*-
# Receita do PyInstaller para o RDF. Uma só análise gera as duas entregas:
#   dist/RDF/              pasta que vai para o instalador: abre rápido, nada é descompactado a cada abertura
#   dist/RDF_portatil.exe  um arquivo só, para usar sem instalar
#
# Uso, com o Tesseract instalado (e os idiomas por e eng):
#   set TESSERACT_DIR=C:\Program Files\Tesseract-OCR
#   python -m PyInstaller --noconfirm --clean packaging\rdf.spec
#
# O que fica de fora do pacote (e por quê) está em packaging/bundle_rules.py. O CI confere cada entrega com
# "RDF.exe --autoteste resultado.json" antes de publicar a versão.

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT / 'packaging'))
sys.path.insert(0, str(ROOT))

import bundle_rules  # noqa: E402
from rdf import APP_VERSION  # noqa: E402

TESSERACT_DIR = os.environ.get('TESSERACT_DIR', '').strip().strip('"')
if not TESSERACT_DIR:
    raise SystemExit('Defina TESSERACT_DIR com a pasta do Tesseract (a que tem o tesseract.exe).')

ICON = str(ROOT / 'assets' / 'icone.ico')
EXCLUDES = [
    'tkinter',
    'tkinterdnd2',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtQuickWidgets',
    'PySide6.QtSql',
    'PySide6.QtTest',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'yaml',  # o numpy só usa, se existir, para formatar numpy.show_config()
]

# As telas das ferramentas e os módulos pré-carregados são importados pelo nome (abertura rápida): o PyInstaller não
# os enxerga sozinho, então todo o pacote rdf entra.
hiddenimports = collect_submodules('rdf')
datas = [(ICON, 'assets')]
binaries = []
for package in ('cv2', 'fitz', 'pymupdf'):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
# O Tesseract roda como programa à parte: entra como arquivos comuns, sem o PyInstaller analisar as DLLs dele.
datas += [(str(source), dest) for source, dest in bundle_rules.tesseract_files(TESSERACT_DIR)]

a = Analysis(
    [str(ROOT / 'rdf_app.py')],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=EXCLUDES,
    noarchive=False,
)
a.binaries = bundle_rules.filter_toc(a.binaries)
a.datas = bundle_rules.filter_toc(a.datas)
pyz = PYZ(a.pure)

def windows_version_info():
    """Versão, nome e fabricante que o Windows mostra nas propriedades do RDF.exe (aba Detalhes)."""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = tuple(int(part) for part in APP_VERSION.split('.')[:4])
    numbers += (0,) * (4 - len(numbers))
    strings = [
        StringStruct('CompanyName', 'RENAPSI'),
        StringStruct('FileDescription', 'RDF - Ferramentas de PDF'),
        StringStruct('FileVersion', APP_VERSION),
        StringStruct('InternalName', 'RDF'),
        StringStruct('OriginalFilename', 'RDF.exe'),
        StringStruct('ProductName', 'Renomeador de Folhas (RDF)'),
        StringStruct('ProductVersion', APP_VERSION),
    ]
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1),
        kids=[
            StringFileInfo([StringTable('041604B0', strings)]),  # português do Brasil, Unicode
            VarFileInfo([VarStruct('Translation', [0x0416, 1200])]),
        ],
    )


version_info = windows_version_info() if sys.platform == 'win32' else None

common = dict(console=False, icon=ICON, version=version_info, upx=False, disable_windowed_traceback=False)

installed = EXE(pyz, a.scripts, [], exclude_binaries=True, name='RDF', **common)
COLLECT(installed, a.binaries, a.datas, name='RDF', upx=False)

EXE(pyz, a.scripts, a.binaries, a.datas, [], name='RDF_portatil', **common)

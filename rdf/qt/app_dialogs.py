"""Diálogos do aplicativo: Configurações, Sobre e Atalhos do teclado.

As configurações valem na hora (sem OK/Cancelar): trocar o tema repinta o app, e cada escolha é gravada nas
preferências do usuário (rdf.core.settings).
"""

import platform
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from rdf import APP_VERSION
from rdf.core import autostart, config, settings
from rdf.qt.widgets import BrandMark

THEME_CHOICES = (('sistema', 'Igual ao Windows'), ('claro', 'Claro'), ('escuro', 'Escuro'))

SHORTCUTS = (
    (
        'Em todo o app',
        (
            ('Ctrl+F  ou  Ctrl+K', 'Buscar uma ferramenta'),
            ('Esc', 'Voltar para o início (pergunta antes se houver trabalho)'),
            ('F1', 'Esta lista de atalhos'),
            ('Ctrl+,', 'Configurações'),
            ('Ctrl+Shift+T', 'Alternar entre tema claro e escuro'),
        ),
    ),
    (
        'Tela inicial',
        (
            ('Enter', 'Abrir a primeira ferramenta da busca'),
            ('Setas', 'Andar entre as ferramentas'),
            ('Ctrl+D', 'Marcar ou desmarcar como favorita'),
        ),
    ),
    (
        'Ferramentas de PDF',
        (
            ('Ctrl+O', 'Adicionar arquivos'),
            ('Ctrl+Enter', 'Executar a ferramenta'),
            ('Delete', 'Tirar os selecionados da lista'),
            ('Ctrl+P', 'Imprimir (em Unir PDF)'),
            ('Ctrl+A', 'Selecionar todas as páginas (nas miniaturas)'),
        ),
    ),
    (
        'Renomear folhas de ponto',
        (
            ('Enter  ou  F2', 'Corrigir os dados do arquivo selecionado'),
            ('F3', 'Ir para o próximo arquivo a revisar'),
            ('Ctrl+L', 'Filtrar o lote por nome'),
            ('Ctrl+  +  /  Ctrl+  −', 'Aumentar ou diminuir a prévia'),
            ('Delete', 'Tirar os selecionados do lote'),
        ),
    ),
)


def _dialog(parent, title, width):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.setMinimumWidth(width)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 22, 24, 20)
    layout.setSpacing(12)
    return dialog, layout


def _title(text):
    label = QLabel(text)
    label.setObjectName('pageTitle')
    return label


def _section(text):
    label = QLabel(text)
    label.setObjectName('groupTitle')
    return label


def _hint(text):
    label = QLabel(text)
    label.setObjectName('hint')
    label.setWordWrap(True)
    return label


def _separator():
    line = QFrame()
    line.setObjectName('vline')
    line.setFixedHeight(1)
    return line


def _open(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class SettingsDialog(QDialog):
    """Configurações do RDF. themeChanged avisa a janela para aplicar o tema escolhido; updatesRequested pede uma
    procura de atualização agora."""

    themeChanged = Signal(str)
    updatesRequested = Signal()

    WIDTH = 580

    def __init__(self, parent=None, tesseract=None):
        super().__init__(parent)
        self.setWindowTitle('Configurações')
        self.setModal(True)
        self.setMinimumWidth(self.WIDTH)
        prefs = settings.current()
        # O conteúdo rola dentro da janela: textos com quebra de linha não ficam cortados e a janela cabe em telas
        # baixas (notebooks com 768 px de altura).
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 20)
        outer.setSpacing(12)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName('optionsContent')
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll, 1)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(24, 22, 24, 4)
        layout.setSpacing(12)
        layout.addWidget(_title('Configurações'))

        layout.addWidget(_section('Aparência'))
        row = QHBoxLayout()
        label = QLabel('Tema')
        label.setObjectName('fieldLabel')
        self.theme_combo = QComboBox()
        self.theme_combo.setAccessibleName('Tema')
        for value, text in THEME_CHOICES:
            self.theme_combo.addItem(text, value)
        self.theme_combo.setCurrentIndex(max(0, [v for v, _t in THEME_CHOICES].index(prefs.get('theme'))))
        self.theme_combo.currentIndexChanged.connect(self._on_theme)
        label.setBuddy(self.theme_combo)
        row.addWidget(label)
        row.addWidget(self.theme_combo, 1)
        layout.addLayout(row)

        layout.addWidget(_separator())
        layout.addWidget(_section('Ferramentas de PDF'))
        self.open_folder = QCheckBox('Abrir a pasta do resultado ao terminar')
        self.open_folder.setChecked(prefs.get('open_folder_after'))
        self.open_folder.toggled.connect(lambda value: settings.current().set('open_folder_after', value))
        layout.addWidget(self.open_folder)

        layout.addWidget(_separator())
        layout.addWidget(_section('Windows'))
        self.autostart = QCheckBox('Iniciar com o Windows, em segundo plano (perto do relógio)')
        self.autostart.setEnabled(autostart.supported())
        self.autostart.setChecked(autostart.is_enabled())
        self.autostart.toggled.connect(self._on_autostart)
        layout.addWidget(self.autostart)
        if not autostart.supported():
            layout.addWidget(_hint('Disponível só no Windows.'))

        layout.addWidget(_separator())
        layout.addWidget(_section('Atualizações'))
        updates_row = QHBoxLayout()
        self.check_updates = QCheckBox('Procurar versões novas automaticamente')
        self.check_updates.setChecked(prefs.get('check_updates'))
        self.check_updates.toggled.connect(lambda value: settings.current().set('check_updates', value))
        updates_row.addWidget(self.check_updates, 1)
        self.updates_button = QPushButton('Procurar agora')
        self.updates_button.clicked.connect(self.updatesRequested)
        updates_row.addWidget(self.updates_button)
        layout.addLayout(updates_row)
        layout.addWidget(
            _hint(
                f'Você está usando a versão {APP_VERSION}. A procura só consulta o GitHub do RDF; nada seu é enviado.'
            )
        )

        layout.addWidget(_separator())
        layout.addWidget(_section('OCR (Tesseract)'))
        self.tesseract_label = _hint(
            f'Encontrado em: {tesseract}'
            if tesseract
            else 'Não encontrado. O OCR e o renomeador precisam dele: reinstale o RDF ou escreva o caminho do '
            'tesseract.exe no arquivo tesseract_path.txt, na pasta do programa.'
        )
        self.tesseract_label.setProperty('tone', 'info' if tesseract else 'error')
        self.tesseract_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.tesseract_label)

        layout.addWidget(_separator())
        layout.addWidget(_section('Dados do aplicativo'))
        layout.addWidget(
            _hint(
                'O RDF guarda aqui o log, a sessão do renomeador (apagada em até 7 dias) e as preferências. Os seus '
                'documentos nunca são enviados para fora deste computador.'
            )
        )
        buttons = QHBoxLayout()
        self.data_button = QPushButton('Abrir pasta de dados')
        self.data_button.clicked.connect(lambda: _open(config.APP_DATA_DIR))
        self.clear_button = QPushButton('Limpar favoritas e recentes')
        self.clear_button.clicked.connect(self._clear_lists)
        buttons.addWidget(self.data_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        layout.addStretch(1)
        close_row = QHBoxLayout()
        close_row.setContentsMargins(24, 0, 24, 0)
        close_row.addStretch(1)
        close = QPushButton('Fechar')
        close.setProperty('variant', 'primary')
        close.setDefault(True)
        close.clicked.connect(self.accept)
        close_row.addWidget(close)
        outer.addLayout(close_row)
        self.fit_height()

    def fit_height(self):
        """Altura certa para a largura da janela (os textos quebram em várias linhas), sem passar da tela."""
        inner = self.WIDTH - 48
        layout = self.content.layout()
        needed = layout.totalHeightForWidth(inner) if layout.hasHeightForWidth() else layout.sizeHint().height()
        height = needed + 90  # botão Fechar e margens
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            height = min(height, screen.availableGeometry().height() - 60)
        self.resize(self.WIDTH, max(360, height))

    def _on_theme(self, index):
        value = self.theme_combo.itemData(index)
        settings.current().set('theme', value)
        self.themeChanged.emit(value)

    def _on_autostart(self, checked):
        autostart.set_enabled(checked)

    def _clear_lists(self):
        prefs = settings.current()
        prefs.set('favorites', [])
        prefs.set('recent', [])
        self.clear_button.setEnabled(False)
        self.clear_button.setText('Listas limpas')


def library_versions():
    """[(componente, versão)] das bibliotecas que o RDF usa, para o Sobre e para relatar problemas."""
    found = [('Python', platform.python_version())]
    try:
        import PySide6

        found.append(('Qt / PySide6', PySide6.__version__))
    except ImportError:
        pass
    try:
        import fitz

        found.append(('PyMuPDF', fitz.VersionBind))
    except (ImportError, AttributeError):
        pass
    for name, module in (('OpenCV', 'cv2'), ('Pillow', 'PIL'), ('NumPy', 'numpy')):
        try:
            found.append((name, __import__(module).__version__))
        except (ImportError, AttributeError):
            continue
    return found


def about_dialog(parent=None, tesseract=None, on_check_updates=None):
    dialog, layout = _dialog(parent, 'Sobre o RDF', 480)
    head = QHBoxLayout()
    head.setSpacing(14)
    head.addWidget(BrandMark(56), 0, Qt.AlignTop)
    names = QVBoxLayout()
    names.setSpacing(2)
    names.addWidget(_title('RDF - Ferramentas de PDF'))
    version = QLabel(f'Versão {APP_VERSION}')
    version.setObjectName('pageLead')
    names.addWidget(version)
    head.addLayout(names, 1)
    layout.addLayout(head)
    layout.addWidget(
        _hint(
            'Caixa de ferramentas de PDF que funciona offline, com o renomeador de folhas de ponto, atestados e '
            'declarações. Os arquivos são processados neste computador e não saem dele.'
        )
    )
    layout.addWidget(_separator())
    layout.addWidget(_section('Componentes'))
    grid = QGridLayout()
    grid.setHorizontalSpacing(18)
    grid.setVerticalSpacing(4)
    rows = library_versions() + [('Tesseract OCR', tesseract or 'não encontrado'), ('Sistema', platform.platform())]
    for index, (name, value) in enumerate(rows):
        left = QLabel(name)
        left.setObjectName('fieldLabel')
        right = QLabel(str(value))
        right.setObjectName('hint')
        right.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right.setWordWrap(True)
        grid.addWidget(left, index, 0, Qt.AlignTop)
        grid.addWidget(right, index, 1)
    grid.setColumnStretch(1, 1)
    holder = QWidget()
    holder.setLayout(grid)
    layout.addWidget(holder)
    layout.addWidget(
        _hint(
            'Versão para avaliação interna, não homologada para uso com dados reais. Bibliotecas de terceiros sob as '
            'suas próprias licenças (PySide6: LGPL; PyMuPDF: AGPL; Tesseract e OpenCV: Apache 2.0).'
        )
    )
    row = QHBoxLayout()
    logs = QPushButton('Abrir pasta do log')
    logs.clicked.connect(lambda: _open(config.LOG_DIR))
    row.addWidget(logs)
    if on_check_updates is not None:
        check = QPushButton('Procurar atualizações')
        check.clicked.connect(on_check_updates)
        row.addWidget(check)
        dialog.updates_button = check
    row.addStretch(1)
    close = QPushButton('Fechar')
    close.setProperty('variant', 'primary')
    close.setDefault(True)
    close.clicked.connect(dialog.accept)
    row.addWidget(close)
    layout.addLayout(row)
    return dialog


def shortcuts_dialog(parent=None):
    dialog, layout = _dialog(parent, 'Atalhos do teclado', 560)
    layout.addWidget(_title('Atalhos do teclado'))
    for title, entries in SHORTCUTS:
        layout.addWidget(_section(title))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        for index, (keys, action) in enumerate(entries):
            key = QLabel(keys)
            key.setObjectName('kbd')
            text = QLabel(action)
            text.setWordWrap(True)
            grid.addWidget(key, index, 0, Qt.AlignLeft | Qt.AlignVCenter)
            grid.addWidget(text, index, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 170)
        holder = QWidget()
        holder.setLayout(grid)
        layout.addWidget(holder)
    row = QHBoxLayout()
    row.addStretch(1)
    close = QPushButton('Fechar')
    close.setProperty('variant', 'primary')
    close.setDefault(True)
    close.clicked.connect(dialog.accept)
    row.addWidget(close)
    layout.addLayout(row)
    return dialog


def tesseract_path():
    """O Tesseract configurado (pytesseract), ou None se não foi encontrado na inicialização."""
    try:
        import pytesseract

        command = pytesseract.pytesseract.tesseract_cmd
    except ImportError:
        return None
    return command if command and Path(command).is_file() else None

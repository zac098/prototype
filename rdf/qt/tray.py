"""Ícone do RDF na bandeja do sistema (perto do relógio).

Com o início automático ligado, o RDF fica aqui em segundo plano: o botão direito do Explorer ("Imprimir com o RDF")
abre a janela na hora, sem esperar o programa carregar. O menu da bandeja também liga e desliga o início automático.
"""

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from rdf.core import autostart
from rdf.core.config import resource_path


class TrayController(QObject):
    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self.window = window
        icon = resource_path('assets', 'icone.ico')
        self.tray = QSystemTrayIcon(QIcon(str(icon)) if icon.is_file() else window.windowIcon(), self)
        self.tray.setToolTip('RDF - Ferramentas de PDF')

        self.menu = QMenu()
        self.open_action = QAction('Abrir o RDF', self.menu)
        self.print_action = QAction('Imprimir ou unir PDFs', self.menu)
        self.autostart_action = QAction('Iniciar com o Windows', self.menu)
        self.autostart_action.setCheckable(True)
        self.quit_action = QAction('Sair', self.menu)
        for action in (self.open_action, self.print_action):
            self.menu.addAction(action)
        self.menu.addSeparator()
        self.menu.addAction(self.autostart_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)

        self.open_action.triggered.connect(self.window.show_from_tray)
        self.print_action.triggered.connect(lambda: self.window.show_tool('merge'))
        self.autostart_action.toggled.connect(self.on_autostart_toggled)
        self.quit_action.triggered.connect(self.window.quit_app)
        self.menu.aboutToShow.connect(self.refresh)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.on_activated)
        self.refresh()
        self.tray.show()

    @staticmethod
    def available():
        return QSystemTrayIcon.isSystemTrayAvailable()

    def refresh(self):
        """O estado da caixa vem sempre do registro (o instalador também pode ter ligado)."""
        self.autostart_action.blockSignals(True)
        self.autostart_action.setChecked(autostart.is_enabled())
        self.autostart_action.setEnabled(autostart.supported())
        self.autostart_action.blockSignals(False)

    def on_autostart_toggled(self, checked):
        autostart.set_enabled(checked)
        self.refresh()
        if checked:
            self.show_message(
                'Início automático ligado',
                'O RDF vai abrir em segundo plano quando o Windows iniciar. Fechar a janela o deixa aqui, perto do relógio.',
            )

    def on_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.window.show_from_tray()

    def show_message(self, title, text):
        if self.tray.supportsMessages():
            self.tray.showMessage(title, text, QSystemTrayIcon.Information, 6000)

    def hide(self):
        self.tray.hide()

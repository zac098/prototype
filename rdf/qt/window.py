"""Janela principal: tela inicial, uma tela por ferramenta, botão Voltar e atalhos."""

import importlib
import time

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from rdf import APP_VERSION
from rdf.core import autostart, settings
from rdf.core.config import resource_path
from rdf.pdftools.registry import TOOLS_BY_ID
from rdf.qt import app_dialogs, theme
from rdf.qt.home import HomePage
from rdf.qt.updater import UpdateController, UpdateDialog, launch_installer

APP_TITLE = f'RDF - Ferramentas de PDF v{APP_VERSION}'
PREFERRED_SIZE = (1500, 940)
MINIMUM_SIZE = (780, 520)
# Tela de cada ferramenta: (módulo, classe). Cada tela só é importada na primeira vez que abre, então a janela aparece
# sem carregar o PyMuPDF, o OpenCV e o Tesseract (que o __main__ pré-carrega em segundo plano logo depois).
CUSTOM_PAGES = {  # ferramentas com tela própria derivada da padrão
    'merge': ('rdf.qt.merge_page', 'MergePage'),
    'metadata': ('rdf.qt.metadata_page', 'MetadataPage'),
}
RENAMER_PAGE = ('rdf.qt.renamer', 'RenamerPage')
DEFAULT_PAGE = ('rdf.qt.tool_page', 'ToolPage')
INCOMING_DELAY_MS = 600  # o Explorer abre o RDF uma vez por arquivo: espera os outros chegarem antes de abrir a tela
CANCEL_WAIT_SECONDS = 20  # quanto esperar a tarefa parar quando o usuário cancela para sair


def page_class(tool):
    """A classe da tela da ferramenta (importa o módulo dela na primeira vez)."""
    module, name = RENAMER_PAGE if tool.special else CUSTOM_PAGES.get(tool.id, DEFAULT_PAGE)
    return getattr(importlib.import_module(module), name)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        icon = resource_path('assets', 'icone.ico')
        if icon.is_file():
            self.setWindowIcon(QIcon(str(icon)))
        self.pages = {}  # id da ferramenta -> tela já criada (guarda o estado ao voltar para o início)
        self.current_id = None
        self._retired = []  # telas que saíram mas ainda têm uma tarefa terminando em segundo plano
        self.tray = None  # TrayController, quando o sistema tem bandeja
        self._quitting = False  # "Sair" da bandeja: fechar de verdade em vez de esconder
        self._tray_hint_shown = False
        self._incoming = []  # arquivos para imprimir que chegaram do menu do botão direito
        self._incoming_timer = QTimer(self)
        self._incoming_timer.setSingleShot(True)
        self._incoming_timer.setInterval(INCOMING_DELAY_MS)
        self._incoming_timer.timeout.connect(self.open_incoming)

        root = QWidget()
        root.setObjectName('root')
        self.setCentralWidget(root)
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.stack = QStackedWidget()
        self.home = HomePage()
        self.home.toolRequested.connect(self.open_tool)
        self.home.themeRequested.connect(self.set_theme)
        self.home.settingsRequested.connect(self.show_settings)
        self.home.aboutRequested.connect(self.show_about)
        self.home.shortcutsRequested.connect(self.show_shortcuts)
        self.home.updatesRequested.connect(self.check_for_updates)
        self.home.updateRequested.connect(self.show_update_dialog)
        self.stack.addWidget(self.home)
        # Atualizações: a procura automática só começa com updater.start() (o __main__ chama; os testes, não).
        self.updater = UpdateController(self)
        self.updater.available.connect(self.on_update_available)
        self.updater.upToDate.connect(self.on_up_to_date)
        self.updater.failed.connect(self.on_update_failed)
        self._open_update_when_found = False  # procura pedida pelo usuário: abre os detalhes assim que achar
        self._update_announced = None  # versão já avisada pela bandeja (uma vez por versão)
        row.addWidget(self.stack, 1)

        for sequence, handler in (
            (Qt.Key_Escape, self.on_escape),
            ('Ctrl+F', self.focus_search),
            ('Ctrl+K', self.focus_search),
            ('F1', self.show_shortcuts),
            ('Ctrl+,', self.show_settings),
            ('Ctrl+Shift+T', self.toggle_theme),
        ):
            QShortcut(QKeySequence(sequence), self, activated=handler)
        settings.current().forget_tools(TOOLS_BY_ID)  # favoritas de ferramentas que não existem mais
        if not self.restore_geometry():
            self.fit_to_screen()

    # ---- tamanho da janela ---------------------------------------------------------------
    def restore_geometry(self):
        """Volta ao tamanho e à posição da última vez. False se não havia nada salvo (ou não serve mais)."""
        saved = settings.current().get('window_geometry')
        if not saved:
            return False
        try:
            if not self.restoreGeometry(QByteArray.fromBase64(saved.encode('ascii'))):
                return False
        except (ValueError, UnicodeEncodeError):
            return False
        area = QGuiApplication.primaryScreen().availableVirtualGeometry()
        if not area.intersects(self.frameGeometry()):  # o monitor onde ela estava foi desligado
            return False
        self.setMinimumSize(min(MINIMUM_SIZE[0], area.width() - 20), min(MINIMUM_SIZE[1], area.height() - 40))
        return True

    def save_geometry(self):
        settings.current().set('window_geometry', bytes(self.saveGeometry().toBase64()).decode('ascii'))

    # ---- tema, configurações e ajuda -----------------------------------------------------
    def set_theme(self, mode):
        settings.current().set('theme', mode)
        return theme.apply(None, mode)

    def toggle_theme(self):
        """Ctrl+Shift+T: alterna entre claro e escuro (sai do modo "igual ao Windows")."""
        return self.set_theme('claro' if theme.is_dark() else 'escuro')

    def make_settings_dialog(self):
        dialog = app_dialogs.SettingsDialog(self, app_dialogs.tesseract_path())
        dialog.themeChanged.connect(lambda mode: theme.apply(None, mode))
        dialog.updatesRequested.connect(self.check_for_updates)
        return dialog

    def show_settings(self):
        dialog = self.make_settings_dialog()
        dialog.exec()
        self.home.sync()  # "Limpar favoritas e recentes" muda a tela inicial

    def show_about(self):
        app_dialogs.about_dialog(self, app_dialogs.tesseract_path(), self.check_for_updates).exec()

    # ---- atualizações ----------------------------------------------------------------------
    def check_for_updates(self):
        """Procura agora (menu de ajuda, Sobre, Configurações): avisa também quando não há novidade ou internet."""
        self._open_update_when_found = True
        self.updater.check(manual=True)

    def on_update_available(self, release):
        self.home.show_update(release)
        if self._open_update_when_found:
            self._open_update_when_found = False
            self.show_update_dialog()
        elif not self.isVisible() and self.tray is not None and self._update_announced != release.version:
            self._update_announced = release.version
            self.tray.show_message(
                'Nova versão do RDF', f'A versão {release.version} está disponível. Abra o RDF para atualizar.'
            )

    def on_up_to_date(self):
        self._open_update_when_found = False
        self.show_notice('Atualizações', f'Você já está com a versão mais nova do RDF ({APP_VERSION}).')

    def on_update_failed(self, message):
        self._open_update_when_found = False
        QMessageBox.warning(self, 'Atualizações', f'Não foi possível procurar atualizações agora.\n\n{message}')

    def make_update_dialog(self, release):
        return UpdateDialog(release, self)

    def show_update_dialog(self):
        """Detalhes da versão nova; se o usuário escolher instalar, fecha o RDF e roda o instalador."""
        release = self.updater.release
        if release is None:
            return None
        dialog = self.make_update_dialog(release)
        dialog.exec()
        if dialog.install_now and dialog.installer:
            self.install_update(dialog.installer)
        return dialog

    def install_update(self, installer):
        """Fecha o RDF com as conferências de sempre (tarefa em andamento, trabalho não salvo) e roda o instalador,
        que abre o app de novo no fim. False se o RDF continuou aberto ou o instalador não abriu."""
        if not self.quit_app():
            self.show_notice(
                'Atualização adiada',
                'O RDF continuou aberto, então a versão nova não foi instalada. O aviso continua na tela inicial.',
            )
            return False
        try:
            launch_installer(installer)
        except OSError as exc:
            QMessageBox.critical(None, 'Atualização', f'Não foi possível abrir o instalador.\n\n{exc}')
            return False
        return True

    def show_shortcuts(self):
        app_dialogs.shortcuts_dialog(self).exec()

    @property
    def back_button(self):
        """O botão Voltar da tela aberta (cada ferramenta tem o seu, dentro do primeiro cartão)."""
        page = self.pages.get(self.current_id)
        return page.back_button if page else None

    def fit_to_screen(self):
        """Tamanho inicial e mínimo conforme a tela (800x600 até 4K); abre centralizada."""
        area = QGuiApplication.primaryScreen().availableGeometry()
        width = min(area.width() - 20, PREFERRED_SIZE[0])
        height = min(area.height() - 40, PREFERRED_SIZE[1])
        self.setMinimumSize(min(MINIMUM_SIZE[0], area.width() - 20), min(MINIMUM_SIZE[1], area.height() - 40))
        self.resize(width, height)
        self.move(area.x() + (area.width() - width) // 2, area.y() + max(0, (area.height() - height) // 2 - 10))

    # ---- navegação -----------------------------------------------------------------------
    def show_home(self):
        self.setWindowTitle(APP_TITLE)
        self.current_id = None
        self.home.sync()  # a ferramenta que acabou de ser usada entra nas recentes
        self.stack.setCurrentWidget(self.home)

    def open_tool(self, tool_id):
        tool = TOOLS_BY_ID[tool_id]
        page = self.pages.get(tool_id)
        if page is None:
            page_type = page_class(tool)
            page = page_type() if tool.special else page_type(tool)
            page.backRequested.connect(self.request_home)
            self.pages[tool_id] = page
            self.stack.addWidget(page)
            if tool.special:  # primeira vez: oferece continuar o lote da última sessão
                QTimer.singleShot(350, self, lambda: self._offer_restore(page))  # morre junto com a janela
        self.current_id = tool_id
        settings.current().record_use(tool_id)
        self.setWindowTitle(f'{tool.title} - {APP_TITLE}')  # o nome da ferramenta fica na barra de título
        self.stack.setCurrentWidget(page)
        return page

    def _offer_restore(self, page):
        if page in self.pages.values():  # o usuário pode ter saído da tela antes de o aviso aparecer
            page.offer_restore_session()

    def on_escape(self):
        """Esc limpa a busca se há texto nela; senão volta ao início (pedindo confirmação se houver trabalho)."""
        if self.current_id is None and self.home.search.text():
            self.home.search.clear()
        elif self.current_id is not None:
            self.request_home()

    def focus_search(self):
        """Ctrl+F (ou Ctrl+K): vai para a tela inicial e põe o cursor na busca."""
        if self.current_id is not None and not self.request_home():
            return
        self.home.search.focus_edit()

    # ---- arquivos vindos do menu do botão direito ("Imprimir com o RDF") -----------------------
    def bring_to_front(self):
        if self.isMinimized() or not self.isVisible():  # minimizada ou escondida na bandeja
            self.showNormal()
        self.raise_()
        self.activateWindow()
        QApplication.alert(self)  # o Windows nem sempre deixa tomar o foco: pelo menos pisca na barra de tarefas

    def receive_print_files(self, files):
        """Chamado a cada pedido de outro RDF (ou do próprio início). Junta os arquivos que chegam em sequência."""
        self.bring_to_front()
        self._incoming.extend(path for path in files if path not in self._incoming)
        if self._incoming:
            self._incoming_timer.start()

    def open_incoming(self):
        files, self._incoming = self._incoming, []
        if files:
            self.open_print_with(files)

    def open_print_with(self, files):
        """Abre "Unir PDF" com os arquivos, onde está o botão Imprimir. Não tira o usuário de outro trabalho sem ele
        concordar."""
        if self.current_id not in (None, 'merge') and not self.request_home():
            self.show_notice(
                'Arquivos para imprimir',
                f'Chegaram {len(files)} arquivo(s) para imprimir, mas você continuou na ferramenta atual. '
                'Abra "Unir PDF" e adicione-os de novo.',
            )
            return False
        page = self.open_tool('merge')
        if page.running:
            self.show_notice(
                'Tarefa em andamento',
                f'Há uma tarefa em andamento em "Unir PDF". Os {len(files)} arquivo(s) novo(s) não foram adicionados.',
            )
            return False
        page.add_paths(files)
        return True

    def show_notice(self, title, text):
        QMessageBox.information(self, title, text)

    # ---- saída de uma ferramenta -----------------------------------------------------------
    def request_home(self):
        """Volta ao início protegendo o trabalho: durante uma tarefa, pergunta se deve cancelá-la; com trabalho
        não salvo, pergunta se deve descartá-lo. Ao sair, a ferramenta é zerada. False se o usuário ficou."""
        page = self.pages.get(self.current_id)
        if page is None:
            self.show_home()
            return True
        if page.running:
            if not self.ask_cancel_to_leave(page):
                return False
            self.stop_and_wait(page)
        elif page.has_unsaved_work():
            choice = self.ask_unsaved_to_leave(page)
            if choice == 'save':
                page.save_work()
                if page.has_unsaved_work():  # o usuário desistiu de salvar ou deu erro: continua na ferramenta
                    return False
            elif choice != 'discard':
                return False
        self.reset_tool(self.current_id)
        return True

    def ask_cancel_to_leave(self, page):
        box = QMessageBox(
            QMessageBox.Warning,
            'Tarefa em andamento',
            'Há uma tarefa em andamento. Se sair da ferramenta agora, ela será cancelada e o que já foi feito '
            'nesta tela será perdido.\n\nO que deseja fazer?',
            QMessageBox.NoButton,
            self,
        )
        leave = box.addButton('Cancelar a tarefa e sair', QMessageBox.DestructiveRole)
        stay = box.addButton('Continuar aqui', QMessageBox.RejectRole)
        box.setDefaultButton(stay)
        box.setEscapeButton(stay)
        box.exec()
        return box.clickedButton() is leave

    def ask_unsaved_to_leave(self, page):
        """'save', 'discard' ou 'stay'."""
        box = QMessageBox(QMessageBox.Warning, 'Trabalho não salvo', page.unsaved_text(), QMessageBox.NoButton, self)
        save = box.addButton(page.save_label, QMessageBox.AcceptRole) if page.save_label else None
        discard = box.addButton('Sair sem salvar', QMessageBox.DestructiveRole)
        stay = box.addButton('Ficar aqui', QMessageBox.RejectRole)
        box.setDefaultButton(save or stay)
        box.setEscapeButton(stay)
        box.exec()
        clicked = box.clickedButton()
        if save is not None and clicked is save:
            return 'save'
        return 'discard' if clicked is discard else 'stay'

    def stop_and_wait(self, page):
        """Cancela a tarefa da tela e espera (por pouco tempo) ela parar de verdade."""
        page.cancel_for_exit()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            deadline = time.monotonic() + CANCEL_WAIT_SECONDS
            while (page.running or not page.is_finished()) and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.01)
        finally:
            QApplication.restoreOverrideCursor()

    def finish_retired(self):
        """Ao fechar: as telas que já saíram, mas ainda terminam uma tarefa cancelada, têm um tempo para parar.

        Elas não podem impedir o fechamento (o usuário nem as vê mais); o que deixarem de temporário é apagado quando
        terminarem, ou pela limpeza da próxima abertura."""
        waiting = [page for page in self._retired if page.running or not page.is_finished()]
        if not waiting:
            return
        for page in waiting:
            page.cancel_for_exit()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            deadline = time.monotonic() + (2 if self.is_ending_session() else CANCEL_WAIT_SECONDS)
            while any(p.running or not p.is_finished() for p in waiting) and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.01)
        finally:
            QApplication.restoreOverrideCursor()

    def reset_tool(self, tool_id):
        """Vai para o início e apaga a tela da ferramenta: ao abrir de novo, ela vem zerada."""
        page = self.pages.pop(tool_id, None)
        self.show_home()
        if page is None:
            return
        page.discard_work()
        self.stack.removeWidget(page)
        page.hide()
        if page.running or not page.is_finished():
            self._retired.append(page)  # ainda terminando em segundo plano: só é apagada quando acabar
        else:
            page.deleteLater()
        self._retired = [old for old in self._retired if old.running or not old.is_finished()]

    # ---- bandeja do sistema ----------------------------------------------------------------
    def attach_tray(self, tray):
        self.tray = tray

    def background_mode(self):
        """Com bandeja e início automático ligado, o X esconde a janela em vez de encerrar o programa."""
        return self.tray is not None and autostart.is_enabled()

    def show_from_tray(self):
        self.bring_to_front()

    def show_tool(self, tool_id):
        """Abre uma ferramenta pelo menu da bandeja, sem tirar o usuário de outro trabalho sem ele concordar."""
        self.bring_to_front()
        if self.current_id not in (None, tool_id) and not self.request_home():
            return None
        return self.open_tool(tool_id)

    def quit_app(self):
        """Sair (menu da bandeja): encerra de verdade, com as mesmas conferências de sempre (tarefa em andamento etc.)."""
        self._quitting = True
        try:
            return self.close()
        finally:
            self._quitting = False

    @staticmethod
    def is_ending_session():
        """True quando o Windows está desligando ou fazendo logoff (ou o instalador pediu para fechar o app)."""
        app = QGuiApplication.instance()
        return bool(app is not None and app.isSavingSession())

    def hide_to_tray(self):
        self.hide()
        if not self._tray_hint_shown and self.tray is not None:
            self._tray_hint_shown = True
            self.tray.show_message(
                'O RDF continua aberto',
                'Ele ficou em segundo plano, perto do relógio. Para sair de vez, clique no ícone com o botão direito e escolha Sair.',
            )

    # ---- fechamento ----------------------------------------------------------------------
    def closeEvent(self, event):
        # Nunca atrapalha o desligamento ou o logoff do Windows: nesses casos fecha de verdade.
        if not self._quitting and not self.is_ending_session() and self.background_mode():
            event.ignore()
            self.hide_to_tray()
            return
        for page in self.pages.values():
            # O renomeador tem fechamento próprio: não fecha no meio da análise e salva a sessão.
            if hasattr(page, 'prepare_close') and not page.prepare_close():
                event.ignore()
                return
        self.finish_retired()
        busy = [
            page
            for page in self.pages.values()
            if getattr(page, 'running', False) and not hasattr(page, 'prepare_close')
        ]
        if busy:
            answer = QMessageBox.warning(
                self,
                'Operação em andamento',
                'Há um arquivo sendo processado. Se fechar agora, ele ficará incompleto.\n\nFechar mesmo assim?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()
        self.save_geometry()
        if self.tray is not None:
            self.tray.hide()  # senão o ícone fica na bandeja até o mouse passar por cima
        QApplication.quit()  # com o fim da última janela desligado (bandeja), é isto que encerra o programa

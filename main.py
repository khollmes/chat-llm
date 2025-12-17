import sys
from datetime import datetime
from pathlib import Path
import re
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLineEdit,
    QPushButton,
    QLabel,
    QFrame,
    QScrollArea,
)
from PyQt5.QtWidgets import QListWidget
from PyQt5.QtWidgets import QListWidgetItem
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, QSize
from PyQt5.QtGui import QFont
from PyQt5 import QtCore
import pickle
import os
import runpod
import json
from llm_worker import LLMWorker
from utils import Chat, Message

    
RUNPOD_API_KEY = 'rpa_CAQGMWQYBNPXSROOLSIK4DPFRSI1Z7LAFO9MRVUV14v5bj'
ENDPOINT_ID = "m5jusuoejnejnx"
BASE_URL = f"https://api.runpod.ai/v2/m5jusuoejnejnx/run"
runpod.api_key = RUNPOD_API_KEY

RUN_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/run"
STREAM_URL_TEMPLATE = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/stream/{{job_id}}"
MAX_TOKEN_LENGTH = 256

chat = Chat()

class MessageBubble(QWidget):
    def __init__(self, text: str, role: str = "user", parent=None):
        super().__init__(parent)
        self.text = text
        self.role = role
        layout = QHBoxLayout(self)
        # Larger lateral margins make bubbles occupy most of the width
        if role.lower() == "user":
            layout.setContentsMargins(22, 6, 12, 6)  # more space on right
        else:
            layout.setContentsMargins(12, 6, 22, 6)  # more space on left

        # create a bubble frame so the background color covers the whole bubble
        bubble_frame = QWidget()
        bubble_layout = QVBoxLayout(bubble_frame)
        bubble_layout.setContentsMargins(8, 6, 8, 6)
        bubble_layout.setSpacing(4)

        token_match = re.search(r"<\\?/?think>", text)
        if token_match and role.lower() == "assistant":
            # split: think_part is text before token, rest is after token
            parts = re.split(r"<\\?/?think>", text, maxsplit=1)
            if len(parts) == 2:
                think_part, rest_part = parts[0].strip(), parts[1].strip()
            else:
                think_part, rest_part = text, ""

            # toggle button row
            toggle_row = QHBoxLayout()
            toggle_row.setContentsMargins(0, 0, 0, 0)
            toggle_btn = QPushButton("Hide")
            toggle_btn.setCheckable(True)
            toggle_btn.setChecked(True)
            toggle_btn.setFixedHeight(22)
            toggle_btn.setMinimumWidth(56)
            # visible semi-opaque background for contrast on dark bubble
            toggle_btn.setStyleSheet(
                "QPushButton{background-color: rgba(255,255,255,0.12); color: #ffffff; border:none; border-radius:10px; padding:2px 8px; font-weight:600;}"
                "QPushButton:pressed{background-color: rgba(255,255,255,0.18); }"
            )
            toggle_btn.setToolTip("Afficher/masquer la partie 'think' de la réponse")
            toggle_row.addWidget(toggle_btn, 0, Qt.AlignLeft)
            toggle_row.addStretch()
            bubble_layout.addLayout(toggle_row)

            think_label = QLabel(think_part)
            think_label.setWordWrap(True)
            think_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            think_label.setStyleSheet("font-style:italic; opacity:0.9;")
            bubble_layout.addWidget(think_label)

            # main content
            main_label = QLabel(rest_part)
            main_label.setWordWrap(True)
            main_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            bubble_layout.addWidget(main_label)

            def on_toggle(checked):
                # when checked True -> visible, label shows 'Hide'
                think_label.setVisible(checked)
                toggle_btn.setText("Hide" if checked else "Show")

            toggle_btn.toggled.connect(on_toggle)

        else:
            # no think token or not assistant: render whole text
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            bubble_layout.addWidget(lbl)

        # style the bubble frame (background + rounded corners)
        bubble_frame.setStyleSheet(self._bubble_style())

        # add bubble frame into the outer layout with stretch depending on role
        if role.lower() == "user":
            layout.addStretch()
            layout.addWidget(bubble_frame, 0)
        else:
            layout.addWidget(bubble_frame, 0)
            layout.addStretch()

    def _bubble_style(self):
        if self.role.lower() == "user":
            bg = "#9BB4C0"
            color = "#07201a"
        else:
            bg = "#703B3B"
            color = "#ffffff"
        return (
            f"background-color: {bg}; color: {color}; padding: 10px 14px; "
            "border-radius: 14px; font-size: 11pt;"
        )


class ChatView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setAcceptDrops(True)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.vlayout = QVBoxLayout(self.container)
        self.vlayout.setContentsMargins(8, 8, 8, 8)
        self.vlayout.setSpacing(6)
        self.vlayout.addStretch()
        self.scroll.setWidget(self.container)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.scroll)

    def add_message(self, message):
        # message is instance of Message or plain string
        if hasattr(message, "role"):
            role = message.role
            text = message.content
        else:
            role = "system"
            text = str(message)

        bubble = MessageBubble(text=text, role=("user" if role.lower() == "user" else "assistant"))
        # insert before the stretch at the end
        self.vlayout.insertWidget(self.vlayout.count() - 1, bubble)
        QtCore.QTimer.singleShot(0, self._scroll_to_bottom)

    def append(self, text: str):
        # append plain line as assistant/system message
        bubble = MessageBubble(text=text, role="assistant")
        self.vlayout.insertWidget(self.vlayout.count() - 1, bubble)
        QtCore.QTimer.singleShot(0, self._scroll_to_bottom)

    def clear(self):
        # remove all widgets except the final stretch
        for i in reversed(range(self.vlayout.count() - 1)):
            w = self.vlayout.itemAt(i).widget()
            if w:
                w.setParent(None)

    def _scroll_to_bottom(self):
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        for url in urls:
            local_path = url.toLocalFile()
            if local_path and local_path.lower().endswith(".txt"):
                self.parent_window.register_document(local_path)
        event.acceptProposedAction()


class ChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Chat avec LLM")
        self.resize(700, 450)
        self.conversation_file_path = None
        self.pending_docs = []
        self.worker = None  
        self.status_label = None  

        self._setup_global_style()
        self._build_ui()

    def _setup_global_style(self):
        BG = "#E1D0B3"
        USER = "#9BB4C0"
        TAB = "#A18D6D"
        ASSISTANT = "#703B3B"
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {BG};
                color: #0f1720;
                font-family: Inter, Helvetica, Arial, sans-serif;
                font-size: 11pt;
            }}

            QListWidget {{
                background-color: transparent;
                border: none;
                color: #0f1720;
            }}

            QScrollArea, QWidget#chat_container {{
                background-color: transparent;
                border: none;
            }}

            QLineEdit {{
                background-color: #ffffff;
                border: 1px solid #e6eaf0;
                border-radius: 10px;
                padding: 10px 12px;
                color: #0f1720;
            }}

            QLineEdit:focus {{
                border: 1px solid {TAB};
            }}

            QPushButton {{
                background-color: {TAB};
                border: none;
                border-radius: 10px;
                padding: 8px 14px;
                color: white;
                font-weight: 600;
            }}

            QPushButton:hover {{
                background-color: {ASSISTANT};
            }}

            QLabel#HeaderTitle {{
                font-size: 14pt;
                font-weight: 700;
                color: #0f1720;
            }}

            QLabel#HeaderSubtitle {{
                color: #475569;
                font-size: 9pt;
            }}

            QLabel#AttachLabel {{
                color: #475569;
                font-size: 9pt;
            }}

            QFrame#line {{
                background-color: #e6eef8;
            }}

            /* left panel (tab) background */
            QWidget#left_panel {{
                background-color: {TAB};
                border-radius: 8px;
                padding: 6px;
            }}

        """)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        header_widget = QWidget()
        header_widget.setObjectName("header_widget")
        header_widget.setFixedHeight(64)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        left_header = QWidget()
        left_h_layout = QVBoxLayout(left_header)
        left_h_layout.setContentsMargins(0, 0, 0, 0)
        left_h_layout.setSpacing(2)


        subtitle_label = QLabel("Glisser-déposer des fichiers .txt dans la zone de conversation.")
        subtitle_label.setObjectName("HeaderSubtitle")
        subtitle_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        left_h_layout.addWidget(subtitle_label)

        header_layout.addWidget(left_header, stretch=1)

        # toggle button always accessible on the right
        self.toggle_conv_btn = QPushButton("Hide")
        self.toggle_conv_btn.setFixedWidth(80)
        self.toggle_conv_btn.clicked.connect(self.toggle_conversation_bar)
        header_layout.addWidget(self.toggle_conv_btn, stretch=0)

        main_layout.addWidget(header_widget)

        line = QFrame()
        line.setObjectName("line")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setFixedHeight(1)
        main_layout.addWidget(line)

        # build a two-column layout: left = conversations list, right = chat area
        content_layout = QHBoxLayout()

        # Left panel (conversations) with a small header
        self.left_panel = QWidget()
        self.left_panel.setObjectName("left_panel")
        left_panel_layout = QVBoxLayout(self.left_panel)
        left_panel_layout.setContentsMargins(6, 6, 6, 6)
        left_panel_layout.setSpacing(6)

        conv_header_layout = QHBoxLayout()
        conv_header_layout.setContentsMargins(6, 6, 6, 6)
        title_conv = QLabel("Conversations")
        title_conv.setObjectName("ConversationsTitle")
        # match the tab background (transparent so panel color shows) and improve spacing
        title_conv.setStyleSheet("background-color: transparent; color: #FBF8F5; font-weight:700; font-size:12pt; padding:4px 6px;")
        title_conv.setFixedHeight(28)
        conv_header_layout.addWidget(title_conv)
        conv_header_layout.addStretch()

        left_panel_layout.addLayout(conv_header_layout)

        self.conversation_list = QListWidget()
        # allow animated width: set maximum but not fixed
        self.conversation_list.setMaximumWidth(260)
        self.conversation_list.itemSelectionChanged.connect(self.on_conversation_selected)
        left_panel_layout.addWidget(self.conversation_list)

        # centered '+' button below the list to create new conversations
        plus_container = QWidget()
        plus_layout = QHBoxLayout(plus_container)
        plus_layout.setContentsMargins(0, 6, 0, 6)
        plus_layout.addStretch()
        plus_btn = QPushButton("+")
        plus_btn.setFixedSize(36, 36)
        plus_btn.setStyleSheet("font-size:18pt; font-weight:700; border-radius:18px;")
        plus_btn.clicked.connect(self.new_conversation)
        plus_layout.addWidget(plus_btn)
        plus_layout.addStretch()
        left_panel_layout.addWidget(plus_container)

        # Right area
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setSpacing(10)

        self.chat_view = ChatView(parent=self)
        right_layout.addWidget(self.chat_view, stretch=1)

        content_layout.addWidget(self.left_panel)
        content_layout.addWidget(right_container, stretch=1)

        main_layout.addLayout(content_layout)

        self.attach_label = QLabel("Aucun document attaché.")
        self.attach_label.setObjectName("AttachLabel")
        right_layout.addWidget(self.attach_label)

        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)

        self.input_line = QLineEdit()
        self.input_line.setPlaceholderText("Écrire un message et appuyer sur Entrée...")
        self.input_line.returnPressed.connect(self.send_message)
        self.input_line.setMinimumHeight(32)

        self.send_button = QPushButton("Envoyer")
        self.send_button.clicked.connect(self.send_message)

        input_layout.addWidget(self.input_line, stretch=1)
        input_layout.addWidget(self.send_button, stretch=0)

        right_layout.addLayout(input_layout)

        self.status_label = QLabel("Idle")
        right_layout.addWidget(self.status_label)

        # populate conversation list from disk (show preview + date)
        self.refresh_conversation_list()

    def send_message(self):
        global chat
        text = self.input_line.text().strip()
        if not text:
            return

        timestamp = datetime.now().strftime("%H:%M:%S")

        attached_docs = list(self.pending_docs)
        self.pending_docs.clear()
        self.update_attach_label()

        line = f"[{timestamp}] You: {text}\n"
        
        self.save_line_to_conversation(line)

        if attached_docs:
            doc_names = ", ".join(Path(p).name for p in attached_docs)
            attachments_line = f"    ↳ Documents attachés : {doc_names}"
            self.append_to_chat(attachments_line)

            for doc in attached_docs:
                p = Path(doc)
                log_line = f"[{timestamp}] DOC_FOR_MESSAGE: {p.name} | PATH: {p.resolve()}"
                # keep log in chat display
                self.append_to_chat(log_line)
        
        chat.messages.append(Message(role="user", content=text, documents=attached_docs if attached_docs else None))
        self.update_chat_display()
        self.input_line.clear()

        if self.worker is not None:
            try:
                # request graceful cancellation of the previous worker
                if hasattr(self.worker, 'cancel'):
                    self.worker.cancel()
                else:
                    self.worker.requestInterruption()   
                # wait a short time for it to stop
                self.worker.wait(3000)
            except Exception:
                # ignore failures during shutdown
                pass
            
        self.worker = LLMWorker(chat=chat,endpoint=runpod.Endpoint(ENDPOINT_ID), MAX_TOKEN_length=MAX_TOKEN_LENGTH)
        self.worker.tokenReceived.connect(self.on_token_received)
        self.worker.statusChanged.connect(self.on_status_changed)
        self.worker.errorOccurred.connect(self.on_error)
        self.worker.finished.connect(lambda: self.worker.deleteLater()) 
        self._response_started = False
        self.worker.start()


    def update_chat_display(self):
        self.chat_view.clear()
        for message in chat.messages:
            self.chat_view.add_message(message)
        try:
            self.save_chat_pickle()
        except Exception as e:
            self.status_label.setText(f"Save error: {e}")

    def ensure_conversation_file(self):
        if self.conversation_file_path is not None:
            return
        conversations_dir = Path("conversations")
        conversations_dir.mkdir(exist_ok=True)
        first_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.conversation_file_path = conversations_dir / f"{first_ts}.pkl"
        try:
            with open(self.conversation_file_path, "wb") as f:
                pickle.dump(chat, f)
        except Exception:
            pass

    def save_chat_pickle(self):
        self.ensure_conversation_file()
        try:
            with open(self.conversation_file_path, "wb") as f:
                pickle.dump(chat, f)
        except Exception:
            raise

    def load_chat_pickle(self, path):
        try:
            with open(path, "rb") as f:
                loaded = pickle.load(f)
                if isinstance(loaded, type(chat)):
                    return loaded
        except Exception:
            return None
        return None

    def refresh_conversation_list(self):
        self.conversation_list.clear()
        conv_dir = Path("conversations")
        if not conv_dir.exists():
            return
        files = sorted(conv_dir.glob("*.pkl"), reverse=True)
        for p in files:
            # try to load and extract a short preview
            preview = ""
            loaded = self.load_chat_pickle(p)
            if loaded and getattr(loaded, "messages", None):
                try:
                    last = loaded.messages[-1]
                    # preview first line or truncated
                    preview = str(last.content).splitlines()[0][:60]
                except Exception:
                    preview = ""
            display = f"{p.stem} — {preview}"
            item = QListWidgetItem()
            item.setSizeHint(QSize(260, 42))
            item.setData(Qt.UserRole, p.name)
            item.setToolTip(f"{p.name}\n{len(loaded.messages) if loaded and getattr(loaded,'messages',None) else 0} messages")
            self.conversation_list.addItem(item)

            # create custom widget with red delete button at left and label
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(4, 4, 4, 4)
            h.setSpacing(8)
            del_btn = QPushButton("✕")
            del_btn.setFixedSize(24, 24)
            del_btn.setStyleSheet("background-color: #ff6b6b; color: white; border: none; border-radius: 12px;")
            # capture path in default arg to avoid late binding
            del_btn.clicked.connect(lambda _checked, path=p: self._delete_conversation_file(path))
            lbl = QLabel(display)
            lbl.setStyleSheet("color: #FBF8F5;")
            h.addWidget(del_btn)
            h.addWidget(lbl)
            h.addStretch()
            self.conversation_list.setItemWidget(item, w)

    def on_conversation_selected(self):
        items = self.conversation_list.selectedItems()
        if not items:
            return
        # use stored filename in UserRole to locate file
        item = items[0]
        stored_name = item.data(Qt.UserRole)
        if not stored_name:
            # fallback to text
            stored_name = item.text()
        path = Path("conversations") / stored_name
        loaded = self.load_chat_pickle(path)
        if loaded is not None:
            global chat
            chat = loaded
            self.conversation_file_path = path
            self.update_chat_display()

    def _delete_conversation_file(self, path: Path):
        """Internal delete helper used by the red cross button on each item."""
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            self.status_label.setText(f"Delete error: {e}")
            return

        # if we deleted the currently open conversation, reset to new empty chat
        if self.conversation_file_path is not None and Path(self.conversation_file_path) == path:
            global chat
            chat = Chat()
            self.conversation_file_path = None
            self.ensure_conversation_file()
            self.update_chat_display()

        self.refresh_conversation_list()

    def new_conversation(self):
        """Create a fresh empty conversation and select it."""
        global chat
        # stop existing worker if present
        if self.worker is not None:
            try:
                if hasattr(self.worker, 'cancel'):
                    self.worker.cancel()
                else:
                    self.worker.requestInterruption()
                self.worker.wait(3000)
            except Exception:
                pass

        chat = Chat()
        # reset current conversation file path so ensure_conversation_file will create a new one
        self.conversation_file_path = None
        self.ensure_conversation_file()
        self.update_chat_display()
        self.refresh_conversation_list()

    def delete_selected_conversation(self):
        """Delete the selected conversation file from disk and update UI."""
        items = self.conversation_list.selectedItems()
        if not items:
            return
        item = items[0]
        stored_name = item.data(Qt.UserRole)
        if not stored_name:
            stored_name = item.text()
        path = Path("conversations") / stored_name
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            self.status_label.setText(f"Delete error: {e}")
            return

        # if we deleted the currently open conversation, reset to new empty chat
        if self.conversation_file_path is not None and Path(self.conversation_file_path) == path:
            global chat
            chat = Chat()
            self.conversation_file_path = None
            self.ensure_conversation_file()
            self.update_chat_display()

        self.refresh_conversation_list()

    def append_to_chat(self, text: str):
        # append a plain line to the chat view (not part of the Chat.messages list)
        self.chat_view.append(text)
        # save after update
        try:
            self.save_chat_pickle()
        except Exception:
            pass

    def toggle_conversation_bar(self):
        # Animate left_panel width from current to 0 (hide) or to target (show)
        max_w = 260
        current = self.left_panel.width()
        # if currently visible (width > 10) -> hide
        if current > 10:
            anim = QPropertyAnimation(self.left_panel, b"maximumWidth")
            anim.setDuration(280)
            anim.setStartValue(current)
            anim.setEndValue(0)
            anim.setEasingCurve(QEasingCurve.InOutCubic)
            anim.start()
            # keep reference
            self._conv_anim = anim
            self.toggle_conv_btn.setText("Show")
        else:
            # show then animate to max_w
            self.left_panel.setMaximumWidth(0)
            anim = QPropertyAnimation(self.left_panel, b"maximumWidth")
            anim.setDuration(280)
            anim.setStartValue(0)
            anim.setEndValue(max_w)
            anim.setEasingCurve(QEasingCurve.InOutCubic)
            anim.start()
            self._conv_anim = anim
            self.toggle_conv_btn.setText("Hide")


    def register_document(self, path: str):
        path_obj = Path(path)
        abs_path = str(path_obj.resolve())

        if abs_path not in self.pending_docs:
            self.pending_docs.append(abs_path)

        self.update_attach_label()

        timestamp = datetime.now().strftime("%H:%M:%S")
        info_line = f"[{timestamp}] Document prêt pour le prochain message : {path_obj.name}"
        self.append_to_chat(info_line)

    @QtCore.pyqtSlot(str)
    def on_token_received(self, text):
        global chat
        current =Message(role="Assistant", content=text)
        
        chat.messages.append(current)
        
        self.save_line_to_conversation(current.__str__().strip())
        self._response_started = True
        self.update_chat_display()
        # ensure UI scrolls to bottom when new tokens/messages arrive
        QtCore.QTimer.singleShot(0, self.chat_view._scroll_to_bottom)
    
    @QtCore.pyqtSlot(str)
    def on_status_changed(self, status):
        self.status_label.setText(f"Status: {status}")


    @QtCore.pyqtSlot(str)
    def on_error(self, msg):
        self.status_label.setText("Error")
        self.chat_view.append(f"\n[ERROR] {msg}")

    def save_line_to_conversation(self, line: str):
        # legacy no-op: we persist whole chat on update_chat_display via pickle
        return

    def update_attach_label(self):
        if not self.pending_docs:
            self.attach_label.setText("Aucun document attaché.")
        else:
            names = ", ".join(Path(p).name for p in self.pending_docs)
            self.attach_label.setText(f"Documents attachés au prochain message : {names}")

    def closeEvent(self, event):
        if self.worker is not None:
            try:
                self.worker.quit()
                self.worker.wait()
            except Exception:
                # worker may have been already deleted on C++ side; ignore
                pass
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ChatWindow()
    window.show()
    sys.exit(app.exec_())
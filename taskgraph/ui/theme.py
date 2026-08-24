APP_STYLESHEET = """
QWidget { background: #171b20; color: #d5dbe3; font-size: 12px; }
QMainWindow, QDockWidget { background: #12161a; }
QToolBar { background: #11151a; border: 0; spacing: 6px; padding: 6px; }
QToolButton, QPushButton {
    background: #26313b; border: 1px solid #394957; border-radius: 4px;
    padding: 6px 10px;
}
QToolButton:hover, QPushButton:hover { background: #31404d; }
QToolButton:pressed, QPushButton:pressed { background: #177f8e; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #10151a; border: 1px solid #36434e; border-radius: 3px;
    padding: 5px; selection-background-color: #168c9c;
}
QTextEdit#notesEditor {
    background: #10151a; border: 1px solid #36434e; border-radius: 3px;
    padding: 7px; selection-background-color: #168c9c;
}
QTreeWidget, QListWidget, QPlainTextEdit {
    background: #11161b; border: 0; alternate-background-color: #151b21;
}
QTreeWidget::item { padding: 4px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #176b78; }
QHeaderView::section { background: #202830; border: 0; padding: 5px; }
QDockWidget::title { background: #202830; padding: 7px; }
QSplitter::handle { background: #0f1216; }
QStatusBar { background: #11151a; }
QScrollBar { background: #12171c; width: 10px; height: 10px; }
QScrollBar::handle { background: #3b4853; border-radius: 5px; min-height: 22px; }
"""

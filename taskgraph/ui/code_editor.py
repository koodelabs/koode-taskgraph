from __future__ import annotations

from qtpy.QtCore import Qt
from qtpy.QtGui import QFontDatabase, QFontMetrics
from qtpy.QtWidgets import QPlainTextEdit, QSizePolicy


class CodeEditor(QPlainTextEdit):
    INDENT = "    "

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(QFontMetrics(font).horizontalAdvance(" ") * 4)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Tab:
            if event.modifiers() & Qt.ShiftModifier:
                self._unindent_selection()
            else:
                self._indent_selection()
            event.accept()
            return
        if event.key() == Qt.Key_Backtab:
            self._unindent_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def _indent_selection(self) -> None:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.insertText(self.INDENT)
            return
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.beginEditBlock()
        cursor.setPosition(start)
        while cursor.position() <= end:
            cursor.movePosition(cursor.StartOfLine)
            cursor.insertText(self.INDENT)
            end += len(self.INDENT)
            if not cursor.movePosition(cursor.NextBlock):
                break
        cursor.endEditBlock()

    def _unindent_selection(self) -> None:
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.beginEditBlock()
        cursor.setPosition(start)
        while cursor.position() <= end:
            cursor.movePosition(cursor.StartOfLine)
            for _index in range(len(self.INDENT)):
                cursor.movePosition(cursor.Right, cursor.KeepAnchor)
                if cursor.selectedText() == " ":
                    cursor.removeSelectedText()
                    end -= 1
                else:
                    cursor.clearSelection()
                    break
            if not cursor.movePosition(cursor.NextBlock):
                break
        cursor.endEditBlock()

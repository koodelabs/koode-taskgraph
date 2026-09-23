"""Code-oriented text editor used by multiline node properties."""

from __future__ import annotations

from qtpy.QtCore import Qt
from qtpy.QtGui import QFontDatabase, QFontMetrics
from qtpy.QtWidgets import QPlainTextEdit, QSizePolicy


class CodeEditor(QPlainTextEdit):
    """Plain-text editor with indentation behavior for Python/code fields.

    Attributes:
        INDENT: Text inserted when the user presses Tab.
    """

    INDENT = "    "

    def __init__(self, text: str = "", parent=None):
        """Create a no-wrap monospace editor initialized with text.

        Args:
            text: Initial editor text.
            parent: Optional Qt parent widget.

        Returns:
            None.
        """
        super().__init__(text, parent)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(QFontMetrics(font).horizontalAdvance(" ") * 4)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def keyPressEvent(self, event) -> None:
        """Handle Tab/Shift+Tab indentation before default key handling.

        Args:
            event: Qt key event delivered to the editor.

        Returns:
            None.
        """
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
        """Indent the cursor line or every selected line.

        Returns:
            None.
        """
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
        """Remove one indentation level from the cursor line or selection.

        Returns:
            None.
        """
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

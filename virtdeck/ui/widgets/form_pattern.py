"""Д8: the shared form pattern for parameterized dialogs.

One QFormLayout per dialog — a single fixed label column; sections are
headers that span both columns (QFormLayout.addRow(widget)), so field
edges stay on one vertical line across the whole dialog instead of
drifting per section (DELIGHT-4/6).
"""

from PySide6.QtWidgets import QLabel

from ..i18n import tr


def add_section(form, title):
    """Append a section header spanning both columns of `form`.

    The header reuses the #sectionTitle QSS rule (live recolor on theme
    switch), so dialogs need no inline styling (A7/Д4).
    """
    header = QLabel(tr(title))
    header.setObjectName("sectionTitle")
    form.addRow(header)
    return header

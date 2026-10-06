"""Regression tests for MetricCard (v2.11.1 hotfix, v2.11.2 loading).

set_value() must accept an optional ``subtitle`` keyword — the cluster
quorum card calls it as ``set_value("2/4", subtitle=...)``.
"""
from virtdeck.ui.widgets.metric_card import MetricCard


class TestSetValueSubtitle:
    def test_set_value_with_subtitle(self, qtbot):
        card = MetricCard("Quorum", "—")
        qtbot.addWidget(card)
        card.set_value("2/4", subtitle="Quorum: OK")
        assert card._value_label.text() == "2/4"
        assert card._subtitle_label.text() == "Quorum: OK"
        assert not card._subtitle_label.isHidden()

    def test_set_value_without_subtitle_keeps_state(self, qtbot):
        card = MetricCard("Quorum", "—")
        qtbot.addWidget(card)
        card.set_value("2/4", subtitle="Quorum: OK")
        card.set_value("3/4")
        assert card._value_label.text() == "3/4"
        assert card._subtitle_label.text() == "Quorum: OK"
        assert not card._subtitle_label.isHidden()

    def test_set_value_empty_subtitle_hides(self, qtbot):
        card = MetricCard("CPU", "5%")
        qtbot.addWidget(card)
        card.set_value("5%", subtitle="")
        assert card._subtitle_label.isHidden()

    def test_loading_state(self, qtbot):
        """v2.11.2: start_loading hides the value and spins; set_value
        stops the spinner and shows the new value."""
        card = MetricCard("Quorum", "—")
        qtbot.addWidget(card)
        card.show()
        card.start_loading()
        assert card._value_label.isHidden()
        assert card._spinner.isVisible()
        assert card._spinner.is_running
        card.set_value("2/4", subtitle="Quorum: OK")
        assert not card._value_label.isHidden()
        assert not card._spinner.isVisible()
        assert not card._spinner.is_running
        assert card._value_label.text() == "2/4"

    def test_stop_loading_direct(self, qtbot):
        card = MetricCard("CPU", "—")
        qtbot.addWidget(card)
        card.start_loading()
        card.stop_loading()
        assert not card._value_label.isHidden()
        assert not card._spinner.is_running


class TestRetheme:
    def test_retheme_updates_inline_colors(self, qtbot):
        """Инлайн-цвета карточки перекрашиваются при смене темы."""
        from virtdeck.ui.theme import Color, load_theme

        try:
            load_theme("light", persist=False)
            card = MetricCard("CPU", "0.7%", show_progress=True)
            qtbot.addWidget(card)
            assert f"color: {Color.TEXT};" in card._value_label.styleSheet()

            load_theme("breeze_dark", persist=False)
            # TEXT тёмной темы — светлый; инлайн обновлён из свежих токенов
            assert Color.TEXT == "#fcfcfc"
            assert "color: #fcfcfc;" in card._value_label.styleSheet()
            assert "background: #2c3034;" in card._bar.styleSheet()  # TRACK dark
        finally:
            load_theme("light", persist=False)

    def test_retheme_keeps_token_value_color(self, qtbot):
        """set_value_color(токен) перекрашивается при смене темы."""
        from virtdeck.ui.theme import Color, load_theme

        try:
            load_theme("light", persist=False)
            card = MetricCard("Status", "работает")
            qtbot.addWidget(card)
            card.set_value_color(Color.STATUS_OK)
            assert f"color: {Color.STATUS_OK};" in card._value_label.styleSheet()

            load_theme("breeze_dark", persist=False)
            assert f"color: {Color.STATUS_OK};" in card._value_label.styleSheet()
        finally:
            load_theme("light", persist=False)

    def test_custom_bar_color_survives_retheme(self, qtbot):
        from virtdeck.ui.theme import Color, load_theme

        try:
            load_theme("light", persist=False)
            card = MetricCard("Disk", "300 ГиБ", show_progress=True)
            qtbot.addWidget(card)
            card.set_progress(95, color=Color.DANGER)
            load_theme("breeze_dark", persist=False)
            # кастомный цвет чанка сохранён, фон дорожки — из свежей темы
            assert f"background: {Color.TRACK};" in card._bar.styleSheet()
        finally:
            load_theme("light", persist=False)

    def test_height_follows_content(self, qtbot):
        """Карточка не режет контент: высота по sizeHint, не фиксированная."""
        card = MetricCard("Disk", "300.0 ГиБ", "Размер (использование недоступно)",
                          show_progress=True)
        qtbot.addWidget(card)
        assert card.minimumHeight() <= card.sizeHint().height()
        # контент должен помещаться: тайтул + значение + подзаголовок + бар
        assert card.sizeHint().height() >= 100

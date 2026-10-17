"""A8: one usage-level contract (75/90, green/amber/red) for every
surface — metric cards, PBS datastores, pool/progress tables."""
from virtdeck.ui.detail_panel._constants import _progress_style
from virtdeck.ui.pbs_panel import _usage_color
from virtdeck.ui.theme import Color, usage_color
from virtdeck.ui.widgets.metric_card import MetricCard

# pytest-qt: a QApplication is required before any widget.


def test_thresholds(qapp):
    assert usage_color(0) == Color.SUCCESS
    assert usage_color(74.9) == Color.SUCCESS
    assert usage_color(75) == Color.WARNING
    assert usage_color(89.9) == Color.WARNING
    assert usage_color(90) == Color.DANGER
    assert usage_color(100) == Color.DANGER


def test_metric_card_bar_follows_contract(qapp):
    card = MetricCard("CPU", show_progress=True)
    card.set_progress(50)
    assert Color.SUCCESS in card._bar.styleSheet()
    card.set_progress(80)
    assert Color.WARNING in card._bar.styleSheet()
    card.set_progress(95)
    assert Color.DANGER in card._bar.styleSheet()


def test_explicit_color_wins(qapp):
    card = MetricCard("CPU", show_progress=True)
    card.set_progress(95, color=Color.ACCENT)
    assert Color.ACCENT in card._bar.styleSheet()


def test_pbs_and_pool_style_share_the_contract(qapp):
    assert _usage_color(0.5) == Color.SUCCESS
    assert _usage_color(0.8) == Color.WARNING
    assert _usage_color(0.95) == Color.DANGER
    assert Color.SUCCESS in _progress_style(50)
    assert Color.WARNING in _progress_style(80)
    assert Color.DANGER in _progress_style(95)

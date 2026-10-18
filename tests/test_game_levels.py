import pytest
from unittest.mock import patch

import bot as bot_module


@pytest.mark.parametrize(
    "plays, category, level, label, symbol",
    [
        (0, "النجوم الفضية", 1, "مبتدئ", "⭐"),
        (499, "النجوم الفضية", 1, "مبتدئ", "⭐"),
        (500, "النجوم الفضية", 2, "لاعب ناشئ", "⭐"),
        (2_500, "النجوم الفضية", 6, "ذهبي", "⭐"),
        (4_500, "النجوم الفضية", 10, "أسطورة فضية", "⭐"),
        (4_999, "النجوم الفضية", 10, "أسطورة فضية", "⭐"),
        (5_000, "النجوم الذهبية", 1, "ذهبي مبتدئ", "🌟"),
        (7_000, "النجوم الذهبية", 5, "ذهبي نادر", "🌟"),
        (9_500, "النجوم الذهبية", 10, "ملك الذهب", "🌟"),
        (10_000, "الماس الأزرق", 1, "ماسي مبتدئ", "💎"),
        (12_500, "الماس الأزرق", 6, "أمير الماس", "💎"),
        (15_000, "الماس البرونزي", 1, "برونزي نادر", "🟤"),
        (20_000, "الماس الأحمر", 1, "أحمر نادر", "❤️"),
        (25_000, "الماس الأسود", 1, "أسود نادر", "🖤"),
        (30_000, "الماس البنفسجي", 1, "بنفسجي نادر", "💜"),
        (35_000, "الماس الملكي", 1, "ملكي نادر", "👑"),
        (40_000, "الماس الأسطوري 1", 1, "مستكشف الماس الأسطوري 1", "🔷"),
        (44_500, "الماس الأسطوري 1", 10, "إمبراطور الماس الأسطوري 1", "🔷"),
        (45_000, "الماس الأسطوري 2", 1, "مستكشف الماس الأسطوري 2", "🔶"),
    ],
)
def test_game_level_category_boundaries(plays, category, level, label, symbol):
    _, actual_level, actual_category, actual_label, actual_symbol, actual_plays = (
        bot_module._game_level_details_from_plays(plays)
    )
    assert actual_plays == plays
    assert actual_level == level
    assert actual_category == category
    assert actual_label == label
    assert actual_symbol == symbol


def test_welcome_symbol_count_matches_level():
    for plays, count in ((0, 1), (500, 2), (4_500, 10), (5_000, 1), (12_500, 6)):
        category_index, level, _category_name, _label, symbol, _ = (
            bot_module._game_level_details_from_plays(plays)
        )
        record = {"player": {"username": "player", "games": {"star": {"plays": plays}}}}
        with patch.object(bot_module, "_game_stats_data", return_value=record):
            welcome = bot_module._game_welcome("player", "North")
        expected_symbol = bot_module.GAME_LEVEL_CATEGORIES[category_index][1]
        assert level == count
        assert symbol == expected_symbol
        assert welcome.endswith(expected_symbol * count)
        assert f"🏅 مستوى الألعاب: {count}" in welcome

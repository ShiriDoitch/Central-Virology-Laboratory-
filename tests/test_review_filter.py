"""מצב פוקוס ומסננים מהירים בממשק (src/review.py): במצב פוקוס שורה תקינה לא מוצגת אף פעם."""
import pandas as pd
import pytest

from src.review import (CONFIRMED_HEX, EMPTY, GREEN_HEX, ORANGE_HEX, YELLOW_HEX, field_titles, filter_counts,
                        next_attention_cell, row_masks, visible_rows)

G, O, Y, C, E = GREEN_HEX, ORANGE_HEX, YELLOW_HEX, CONFIRMED_HEX, EMPTY


def table(*rows):
    """כל שורה: הצבע של כל השדות, אלא אם הוחלפו שדות לפי אינדקס {i: צבע}."""
    titles = field_titles()
    data = []
    for base, changes in rows:
        row = {t: base for t in titles}
        row.update({titles[i]: c for i, c in changes.items()})
        row["עמוד"] = ""                                   # עמודת העמוד: בלי סטטוס, לא נחשבת "ריק"
        data.append(row)
    return pd.DataFrame(data)


COLORS = table((G, {}),            # 0: כולה ירוקה
               (G, {1: O}),        # 1: שדה כתום
               (G, {0: C}),        # 2: ירוק + מאושר = תקין
               (G, {3: Y}),        # 3: צהוב
               (G, {2: E}),        # 4: שדה ריק
               (C, {}))            # 5: כולה מאושרת = תקינה


def shown(status="all", focus=False):
    return list(COLORS.index[visible_rows(COLORS, status, focus)])


def test_focus_mode_hides_every_clean_row_and_keeps_every_row_needing_attention():
    assert shown(focus=True) == [1, 3, 4]
    assert not set(shown(focus=True)) & set(COLORS.index[row_masks(COLORS)["green"]])


@pytest.mark.parametrize("status", ["all", "green", "orange", "yellow", "empty"])
def test_focus_never_shows_a_clean_row_under_any_filter(status):
    clean = set(COLORS.index[row_masks(COLORS)["green"]])
    assert not set(shown(status, focus=True)) & clean


def test_quick_filters_without_focus():
    assert shown("all") == [0, 1, 2, 3, 4, 5]
    assert shown("green") == [0, 2, 5]
    assert shown("orange") == [1] and shown("yellow") == [3] and shown("empty") == [4]


def test_page_column_does_not_count_as_an_empty_field():
    assert shown("empty") == [4]


def test_counts_on_the_chips_match_what_the_table_shows():
    assert filter_counts(COLORS) == {"all": 6, "green": 3, "orange": 1, "yellow": 1, "empty": 1}
    assert filter_counts(COLORS, focus=True) == {"all": 3, "green": 0, "orange": 1, "yellow": 1, "empty": 1}


def test_next_cell_walks_in_reading_order_and_wraps():
    t = field_titles()
    rows = list(COLORS.index)
    assert next_attention_cell(COLORS, rows, None) == (1, t[1])
    assert next_attention_cell(COLORS, rows, (1, t[1])) == (3, t[3])
    assert next_attention_cell(COLORS, rows, (4, t[2])) == (1, t[1])
    assert next_attention_cell(table((G, {})), [0], None) is None

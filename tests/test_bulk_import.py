import pytest

from app.bulk_import import (
    BulkCSVError,
    MAX_BULK_CSV_BYTES,
    MAX_BULK_ROWS,
    parse_bulk_csv,
    split_bulk_values,
)


def test_parse_bulk_csv_accepts_utf8_bom_semicolon_and_localized_headers():
    rows = parse_bulk_csv(
        '\ufeffПосилання;Назва;Мови;Формати\r\n'
        'https://example.com/products/one;Товар один;ua|pl;desktop|mobile\r\n'
    )

    assert rows == [{
        '_row': 2,
        'source_url': 'https://example.com/products/one',
        'name': 'Товар один',
        'languages': 'ua|pl',
        'variants': 'desktop|mobile',
    }]


def test_parse_bulk_csv_preserves_quoted_commas_and_multiline_names():
    rows = parse_bulk_csv(
        'source_url,name\n'
        'https://example.com/products/one,"Printer, revised\n2026 edition"\n'
    )

    assert rows[0]['source_url'] == 'https://example.com/products/one'
    assert rows[0]['name'] == 'Printer, revised\n2026 edition'
    # csv.reader reports the physical line on which a multiline record ends.
    assert rows[0]['_row'] == 3


def test_parse_bulk_csv_ignores_empty_records_but_keeps_physical_row_numbers():
    rows = parse_bulk_csv(
        'url,name\r\n'
        '\r\n'
        'https://example.com/a,First\r\n'
        '   ,   \r\n'
        'https://example.com/b,Second\r\n'
    )

    assert [(row['_row'], row['source_url']) for row in rows] == [
        (3, 'https://example.com/a'),
        (5, 'https://example.com/b'),
    ]


@pytest.mark.parametrize(
    ('csv_text', 'message'),
    [
        ('name\nProduct\n', 'url або source_url'),
        ('url,source_url\nhttps://example.com/a,https://example.com/b\n', 'дублюються'),
        ('source_url,_row\nhttps://example.com/a,abc\n', 'Службові колонки'),
        ('source_url,_parse_error\nhttps://example.com/a,nope\n', 'Службові колонки'),
        ('\x00source_url\nhttps://example.com/a\n', 'нульовий символ'),
        ('source_url\n', 'жодного товару'),
    ],
)
def test_parse_bulk_csv_rejects_structurally_invalid_files(csv_text, message):
    with pytest.raises(BulkCSVError, match=message):
        parse_bulk_csv(csv_text)


def test_parse_bulk_csv_marks_extra_nonempty_cells_as_a_row_error():
    rows = parse_bulk_csv('source_url,name\nhttps://example.com/a,First,unexpected\n')

    assert rows[0]['_parse_error'] == 'У рядку більше значень, ніж колонок у заголовку'


def test_parse_bulk_csv_enforces_row_limit():
    csv_text = 'source_url\n' + ''.join(
        f'https://example.com/products/{index}\n' for index in range(MAX_BULK_ROWS + 1)
    )

    with pytest.raises(BulkCSVError, match=f'не більше {MAX_BULK_ROWS}'):
        parse_bulk_csv(csv_text)


def test_parse_bulk_csv_enforces_utf8_byte_limit():
    csv_text = 'source_url,name\nhttps://example.com/a,' + ('я' * MAX_BULK_CSV_BYTES)

    with pytest.raises(BulkCSVError, match='512 КБ'):
        parse_bulk_csv(csv_text)


def test_parse_bulk_csv_rejects_unterminated_quoted_field():
    with pytest.raises(BulkCSVError, match='Помилка CSV'):
        parse_bulk_csv('source_url,name\nhttps://example.com/a,"unfinished\n')


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('ua|ru|pl', ['ua', 'ru', 'pl']),
        ('desktop, mobile', ['desktop', 'mobile']),
        (' en-GB ; de ', ['en-GB', 'de']),
        ('', []),
    ],
)
def test_split_bulk_values_accepts_common_csv_cell_separators(raw, expected):
    assert split_bulk_values(raw) == expected

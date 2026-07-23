"""CSV parsing for the project bulk-import workflow.

The parser deliberately knows nothing about SQLAlchemy or FastAPI.  It turns a
small, human-authored CSV export into normalized row dictionaries while the API
layer remains responsible for product/style validation and queueing.
"""
from __future__ import annotations

import csv
import io
import re


MAX_BULK_CSV_BYTES = 512 * 1024
MAX_BULK_ROWS = 100
_RESERVED_HEADERS = {'_row', '_parse_error'}


class BulkCSVError(ValueError):
    """The file itself cannot be interpreted as a bulk-import table."""


_COLUMN_ALIASES = {
    'url': 'source_url',
    'source_url': 'source_url',
    'product_url': 'source_url',
    'link': 'source_url',
    'посилання': 'source_url',
    'ссылка': 'source_url',
    'name': 'name',
    'product_name': 'name',
    'назва': 'name',
    'название': 'name',
    'style': 'style',
    'style_id': 'style',
    'стиль': 'style',
    'languages': 'languages',
    'language': 'languages',
    'мови': 'languages',
    'языки': 'languages',
    'variants': 'variants',
    'formats': 'variants',
    'формати': 'variants',
    'форматы': 'variants',
    'text_model': 'text_model',
    'image_model': 'image_model',
    'image_quality': 'image_quality',
    'custom_hero_url': 'custom_hero_url',
    'hero_url': 'custom_hero_url',
    'custom_feature_url': 'custom_feature_url',
    'feature_url': 'custom_feature_url',
}


def _header_key(value: str) -> str:
    value = str(value or '').lstrip('\ufeff').strip().lower()
    return re.sub(r'[\s-]+', '_', value)


def _dialect(text: str):
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=',;\t')
    except csv.Error:
        first = next((line for line in sample.splitlines() if line.strip()), '')
        delimiter = max((',', ';', '\t'), key=first.count)

        class Fallback(csv.excel):
            pass

        Fallback.delimiter = delimiter
        return Fallback


def parse_bulk_csv(text: str) -> list[dict[str, str | int]]:
    """Return normalized rows with their physical CSV line in ``_row``.

    Empty lines are ignored. Unknown columns are preserved under their
    normalized header so future API versions can add fields without changing
    the parser. A row with non-empty cells beyond the header receives a private
    ``_parse_error`` marker and can be rejected without blocking other rows.
    """
    if not isinstance(text, str) or not text.strip():
        raise BulkCSVError('CSV-файл порожній')
    if '\x00' in text:
        raise BulkCSVError('CSV містить неприпустимий нульовий символ')
    if len(text.encode('utf-8')) > MAX_BULK_CSV_BYTES:
        raise BulkCSVError('CSV більший за 512 КБ')

    try:
        # ``strict`` turns malformed quoting into a useful row error instead of
        # silently swallowing the rest of the file into one cell.
        reader = csv.reader(io.StringIO(text, newline=''), dialect=_dialect(text), strict=True)
        raw_headers = next(reader, None)
    except (csv.Error, UnicodeError) as exc:
        raise BulkCSVError(f'Не вдалося прочитати CSV: {exc}') from exc
    if not raw_headers:
        raise BulkCSVError('CSV не містить заголовка')

    headers = [_COLUMN_ALIASES.get(_header_key(value), _header_key(value)) for value in raw_headers]
    if any(not value for value in headers):
        raise BulkCSVError('У заголовку CSV є порожня назва колонки')
    reserved = sorted(set(headers) & _RESERVED_HEADERS)
    if reserved:
        raise BulkCSVError('Службові колонки CSV заборонені: ' + ', '.join(reserved))
    duplicates = sorted({value for value in headers if headers.count(value) > 1})
    if duplicates:
        raise BulkCSVError('Колонки CSV дублюються: ' + ', '.join(duplicates))
    if 'source_url' not in headers:
        raise BulkCSVError('Додайте обов’язкову колонку url або source_url')

    rows: list[dict[str, str | int]] = []
    try:
        for values in reader:
            line = reader.line_num
            if not any(str(value or '').strip() for value in values):
                continue
            row: dict[str, str | int] = {'_row': line}
            for index, header in enumerate(headers):
                row[header] = str(values[index] if index < len(values) else '').strip()
            extras = [str(value).strip() for value in values[len(headers):] if str(value).strip()]
            if extras:
                row['_parse_error'] = 'У рядку більше значень, ніж колонок у заголовку'
            rows.append(row)
            if len(rows) > MAX_BULK_ROWS:
                raise BulkCSVError(f'За один імпорт можна додати не більше {MAX_BULK_ROWS} товарів')
    except csv.Error as exc:
        raise BulkCSVError(f'Помилка CSV біля рядка {reader.line_num}: {exc}') from exc

    if not rows:
        raise BulkCSVError('CSV не містить жодного товару')
    return rows


def split_bulk_values(value: str) -> list[str]:
    """Split a quoted CSV cell such as ``ua|ru`` or ``desktop, mobile``."""
    return [part for part in re.split(r'[|,;\s]+', str(value or '').strip()) if part]

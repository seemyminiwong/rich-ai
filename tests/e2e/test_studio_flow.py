"""Playwright-сценарій — головна страховка фронтенду.

grep-smoke тричі мовчки промахувався (перевірка сама дрейфувала і завжди
проходила). Цей сценарій ганяє СПРАВЖНІЙ app.js у справжньому браузері проти
справжнього API і ловить саме ті класи регресій, які ми ловили руками:

- зникнення функцій діалогу при перекроюванні шаблонів (ReferenceError);
- затінення <dialog id=...> однойменною функцією (TypeError на .close());
- стирання URL з поля при перемиканні режимів Простий/Розширений;
- відсутність вибору стилю в простому режимі.
- розрив двокрокового CSV-імпорту «перевірити → створити валідні рядки».

Колектор page.on('pageerror') — це і є детектор: будь-який неперехоплений
виняток у браузері валить тест із текстом помилки.

Запускається лише в e2e-джобі CI (E2E_BASE_URL задано): звичайний `pytest tests`
пропускає файл, бо Playwright і живий сервер там не потрібні.
"""
import os

import pytest

BASE = os.environ.get('E2E_BASE_URL')
pytestmark = pytest.mark.skipif(not BASE, reason='E2E_BASE_URL not set - browser job only')


@pytest.fixture()
def browser_page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        console = []
        page.on('console', lambda msg: console.append(f'[{msg.type}] {msg.text}'))

        def note_api_response(response):
            if '/api/' not in response.url:
                return
            line = f'[http {response.status}] {response.request.method} {response.url}'
            if response.status >= 400:
                line += f' body={response.request.post_data!r}'
            console.append(line)

        page.on('response', note_api_response)
        yield page, errors
        # Post-mortem for CI: whatever the page looked like when the test ended.
        try:
            page.screenshot(path='/tmp/e2e-last-state.png', full_page=True)
            with open('/tmp/e2e-console.log', 'w') as fh:
                fh.write('\n'.join(console[-200:]))
        except Exception:
            pass
        browser.close()


def test_login_dialog_modes_create_and_settings(browser_page):
    page, errors = browser_page

    # --- Логін ---------------------------------------------------------------
    page.goto(BASE)
    page.fill('input[name=email]', os.environ['ADMIN_EMAIL'])
    page.fill('input[name=password]', os.environ['ADMIN_PASSWORD'])
    page.click('button:has-text("Увійти")')
    page.wait_for_selector('h1:has-text("Проєкти")')
    assert errors == [], f'JS errors after login: {errors}'

    # --- Діалог: перемикання режимів не сміє стерти URL ----------------------
    page.click('button:has-text("Новий проєкт")')
    page.wait_for_selector('#newProject[open]')
    url_value = 'https://example.com/product-123'
    page.fill('#newProject input[name=source_url]', url_value)

    page.click('#newProject button:has-text("Розширений")')
    page.wait_for_selector('#newProject select[name=text_model]')
    assert page.input_value('#newProject input[name=source_url]') == url_value, \
        'Перемикання в Розширений стерло URL'

    page.click('#newProject button:has-text("Простий")')
    page.wait_for_selector('#newProject .preset-grid')
    assert page.input_value('#newProject input[name=source_url]') == url_value, \
        'Перемикання назад у Простий стерло URL'
    # Вибір стилю є і в простому режимі; 4 керовані стилі засіяно при старті.
    assert page.locator('#newProject select[name=style_id] option').count() >= 4

    page.click('#newProject button[aria-label="Закрити"]')
    page.wait_for_selector('#newProject[open]', state='detached')
    assert errors == [], f'JS errors around the create dialog: {errors}'

    # --- Створення проєкту і відкриття його сторінки -------------------------
    page.click('button:has-text("Новий проєкт")')
    page.wait_for_selector('#newProject[open]')
    page.fill('#newProject input[name=source_url]', url_value)
    page.click('#newProject button:has-text("Створити й запустити")')
    # Без worker проєкт чесно висить у черзі — сторінка проєкту вже відкрита.
    # Червоний тост = API відхилив створення; впасти треба з ЙОГО текстом,
    # а не з німим таймаутом на бейджі.
    page.wait_for_selector('.badge.queued, .badge.processing, .toast.bad', timeout=30_000)
    bad_toast = page.locator('.toast.bad')
    if bad_toast.count():
        raise AssertionError(f'API відхилив створення проєкту: {bad_toast.first.inner_text()}')
    assert errors == [], f'JS errors after project creation: {errors}'

    # --- Масовий CSV: спочатку точне превʼю, потім створення валідних рядків --
    page.click('aside nav button:has-text("Проєкти")')
    page.wait_for_selector('h1:has-text("Проєкти")')
    page.click('button:has-text("Імпорт CSV")')
    dialog = page.get_by_role('dialog', name='Імпорт проєктів із CSV')
    dialog.wait_for()
    assert page.locator('#bulkProjectDialog').get_attribute('aria-describedby') == 'bulkProjectDialogNote'
    page.locator('#bulkCsvFile').focus()
    assert page.locator('#bulkCsvFile').evaluate('node => document.activeElement === node'), \
        'Нативний вибір CSV має отримувати клавіатурний фокус'
    bulk_requests = []

    def capture_bulk_request(request):
        if request.method == 'POST' and request.url.endswith('/api/projects/bulk-import'):
            bulk_requests.append(request.post_data_json)

    page.on('request', capture_bulk_request)
    csv_data = (
        '\ufeffsource_url;name;languages;variants\r\n'
        'https://example.com/bulk-e2e-one;Bulk E2E One;ua|pl;desktop\r\n'
        'not-a-public-url;Broken row;ua;desktop\r\n'
        'https://example.com/bulk-e2e-two;Bulk E2E Two;ru;mobile\r\n'
    ).encode('utf-8')
    page.set_input_files('#bulkCsvFile', {
        'name': 'products-e2e.csv',
        'mimeType': 'text/csv',
        'buffer': csv_data,
    })
    page.click('#bulkActions button:has-text("Перевірити CSV")')
    page.wait_for_selector('#bulkActions button:has-text("Створити проєкти")', timeout=30_000)
    preview_metrics = page.locator('#bulkResult .bulk-summary > div')
    assert preview_metrics.nth(0).locator('b').inner_text() == '2', \
        'Превʼю мусить знайти два валідні рядки'
    assert preview_metrics.nth(1).locator('b').inner_text() == '1', \
        'Превʼю мусить показати один невалідний рядок'
    assert 'not-a-public-url' in page.locator('#bulkResult').inner_text()
    preview_table = page.locator('#bulkResult .bulk-table').first.inner_text()
    assert all(label in preview_table for label in ('Українська', 'Польська', 'Російська',
                                                     'Десктоп', 'Мобільна')), \
        'Превʼю мусить показувати нормалізовані мови й формати кожного рядка'
    batch_id = page.evaluate('state.bulk.preview.batch_id')
    frozen_snapshot = page.evaluate(
        'state.bulk.snapshot.batch_id === state.bulk.preview.batch_id'
        ' && Object.isFrozen(state.bulk.snapshot)'
        ' && Object.isFrozen(state.bulk.snapshot.languages)'
        ' && Object.isFrozen(state.bulk.snapshot.variants)'
    )
    assert batch_id and frozen_snapshot, \
        'Підтвердження мусить зберігати незмінний snapshot із batch_id'

    page.click('#bulkActions button:has-text("Створити проєкти")')
    page.wait_for_selector('#bulkResult h3:has-text("Створені проєкти")', timeout=30_000)
    assert len(bulk_requests) == 2 and bulk_requests[1].get('batch_id') == batch_id, \
        'Commit мусить повторно передавати batch_id із preview'
    result_metrics = page.locator('#bulkResult .bulk-summary > div')
    assert result_metrics.nth(0).locator('b').inner_text() == '2', \
        'Після підтвердження мають створитися рівно два проєкти'
    first_project_ids = page.evaluate('(state.bulk.result.projects || []).map(x => x.id)')
    replay = page.evaluate(
        """async payload => await api('/api/projects/bulk-import', {
            method: 'POST', body: JSON.stringify(payload)
        })""",
        bulk_requests[1],
    )
    assert replay.get('idempotent_replay') is True
    assert [project['id'] for project in replay.get('projects', [])] == first_project_ids, \
        'Повтор утраченого commit-відповіді мусить повернути ті самі проєкти'
    mismatched = {**bulk_requests[1], 'csv_text': bulk_requests[1]['csv_text'] + '\nhttps://example.com/other,Other'}
    mismatch_status = page.evaluate(
        """async payload => {
            const response = await fetch('/api/projects/bulk-import', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', Authorization: `Bearer ${state.token}`},
                body: JSON.stringify(payload)
            });
            return response.status;
        }""",
        mismatched,
    )
    assert mismatch_status == 409, 'Той самий batch_id з іншим CSV мусить бути відхилений'
    projects_after_replay = page.evaluate("async () => await api('/api/projects')")
    assert sum(project['source_url'] == 'https://example.com/bulk-e2e-one' for project in projects_after_replay) == 1
    assert sum(project['source_url'] == 'https://example.com/bulk-e2e-two' for project in projects_after_replay) == 1
    page.click('#bulkActions button:has-text("Готово")')
    page.wait_for_selector('#bulkProjectDialog[open]', state='detached')
    page.wait_for_selector('.project:has-text("https://example.com/bulk-e2e-one")')
    page.wait_for_selector('.project:has-text("https://example.com/bulk-e2e-two")')
    assert errors == [], f'JS errors around bulk CSV import: {errors}'

    # --- Налаштування: сторінка рендериться, стрічка технологій на місці -----
    page.click('aside nav button:has-text("Налаштування")')
    page.wait_for_selector('h2:has-text("Стан системи")')
    page.wait_for_selector('.techloop-item')
    assert errors == [], f'JS errors on the settings page: {errors}'

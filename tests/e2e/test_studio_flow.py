"""Playwright-сценарій — головна страховка фронтенду.

grep-smoke тричі мовчки промахувався (перевірка сама дрейфувала і завжди
проходила). Цей сценарій ганяє СПРАВЖНІЙ app.js у справжньому браузері проти
справжнього API і ловить саме ті класи регресій, які ми ловили руками:

- зникнення функцій діалогу при перекроюванні шаблонів (ReferenceError);
- затінення <dialog id=...> однойменною функцією (TypeError на .close());
- стирання URL з поля при перемиканні режимів Простий/Розширений;
- відсутність вибору стилю в простому режимі.

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
        yield page, errors
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
    page.wait_for_selector('.badge.queued, .badge.processing', timeout=30_000)
    assert errors == [], f'JS errors after project creation: {errors}'

    # --- Налаштування: сторінка рендериться, стрічка технологій на місці -----
    page.click('aside nav button:has-text("Налаштування")')
    page.wait_for_selector('h2:has-text("Стан системи")')
    page.wait_for_selector('.techloop-item')
    assert errors == [], f'JS errors on the settings page: {errors}'

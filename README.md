# ARTLINE Rich Studio v11.2

Внутрішня платформа для генерації, перевірки, версіонування та зберігання rich-контенту.

## Основні можливості

- WebUI построен на дизайн-токенах из фирменной палитры ARTLINE.
- Центрированная рабочая область шириной до 1380 px.
- Автоматическое название проекта после анализа товарной страницы.
- Динамический список доступных OpenAI-моделей через Models API с fallback на `.env`.
- Отдельная глобальная медиатека всех исходных, собственных и AI-изображений.
- Hero/Feature prompts находятся только в стилях и являются необязательными.
- Можно указать собственные Hero/Feature URL при создании проекта.
- AI Style Generator, AI Improve Style, Style Score и preview стиля.
- Прямое создание пользователя администратором и регистрация по приглашениям.
- Live progress проекта, RU/UA/PL, Desktop/Mobile, HTML versions, review и usage.

## Быстрый запуск

```bash
cp .env.example .env
nano .env
chmod +x deploy-truenas.sh
./deploy-truenas.sh
```

WebUI: `http://SERVER_IP:3000`

API docs: `http://SERVER_IP:8000/docs`

## Обязательные переменные

```env
POSTGRES_DB=richstudio
POSTGRES_USER=richstudio
POSTGRES_PASSWORD=replace-me
DB_SCHEMA=richstudio_v11_2
REDIS_URL=redis://redis:6379/0
JWT_SECRET=replace-with-long-random-secret
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=replace-me
OPENAI_API_KEY=
```

## Изображения

Логіка пріоритету:

1. Власний URL зображення проєкту.
2. Редагування реального фото товару через OpenAI Images Edit за prompt вибраного стилю.
3. Оригінальне фото зі сторінки товару.

Якщо реальне фото товару не вдалося завантажити або Images Edit завершився помилкою, система не створює вигаданий товар, а залишає оригінальне фото.

## Модели

`GET /api/models` пытается загрузить доступные модели текущего OpenAI API-аккаунта и объединяет их со списками из `.env`.

## База данных

v11 использует отдельную PostgreSQL-схему `richstudio_v11_2`, поэтому тестовые таблицы предыдущих сборок не конфликтуют с новой версией.

## Критичні виправлення v11.2

- The ARTLINE palette JSON is copied into `config/artline-palette.json` and mapped to WebUI design tokens.
- Media Library now has filtering and an asset inspector with prompt, model, resolution, cost and download.
- OpenAI models are loaded dynamically and can also be entered manually by model ID.
- Reasoning models are shown separately in Settings.
- Style Generator accepts product category, mood and reference URL.
- Style quality analysis, recommendations and version history are available in the style editor.
- Administrators can create users, reset passwords, disable accounts and delete accounts.
- Project names continue to be resolved automatically from parsed product data.

The implementation is a functional development build. External OpenAI calls and TrueNAS networking must still be verified in the deployment environment.


### Додатково виправлено

- Hero та Feature створюються лише через редагування реального фото товару.
- Попередній перегляд коректно прокручується до останнього блоку.
- Кнопка «Відкрити окремо» формує повний HTML-документ у новій вкладці.
- У WebUI використовується офіційний логотип ARTLINE.
- Інтерфейс локалізовано українською.
- Картка «Докладніше» працює і в глобальній медіатеці, і всередині проєкту.
- Review повертає зрозумілі помилки замість загального Internal server error.
- Збереження HTML та стилів має захист від повторного натискання й коректну нумерацію версій.

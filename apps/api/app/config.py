import json
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_TEXT_PRICING = {
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5": {"input": 1.25, "output": 10.00},
}

DEFAULT_IMAGE_PRICING = {
    "gpt-image-1": {"low": 0.02, "medium": 0.07, "high": 0.19},
    "gpt-image-1-mini": {"low": 0.005, "medium": 0.015, "high": 0.04},
    # Gemini image models bill a flat rate per image: they have no quality tiers,
    # so every tier resolves to the same figure.
    # Non-square tiers (our Hero/Feature are 1536x1024 or 1024x1536) plus an edit
    # surcharge: gpt-image-2 always ingests the reference photo at high fidelity.
    "gpt-image-2": {"low": 0.02, "medium": 0.06, "high": 0.20},
    "gemini-2.5-flash-image": {"low": 0.039, "medium": 0.039, "high": 0.039},
    "gemini-3.1-flash-image-preview": {"low": 0.045, "medium": 0.045, "high": 0.045},
    "gemini-3.1-flash-lite-image": {"low": 0.02, "medium": 0.02, "high": 0.02},
    "gemini-3-pro-image-preview": {"low": 0.134, "medium": 0.134, "high": 0.134},
}


# Values shipped in the repo. Anyone can read them on GitHub, so a deployment that
# still carries one is not protected by it at all - a default JWT_SECRET lets a
# stranger sign themselves an admin token. Checked at startup, see check_secrets().
SHIPPED_DEFAULTS = {
    'jwt_secret': 'replace-with-a-long-random-secret',
    'admin_password': 'change-this-admin-password',
    'postgres_password': 'change-this-db-password',
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = ''
    postgres_host: str = 'postgres'
    postgres_port: int = 5432
    postgres_db: str = 'richstudio'
    postgres_user: str = 'richstudio'
    postgres_password: str = 'change-this-db-password'
    db_schema: str = 'richstudio_v11_2'
    redis_url: str = 'redis://redis:6379/0'
    jwt_secret: str = 'replace-with-a-long-random-secret'
    admin_email: str = 'admin@example.com'
    admin_password: str = 'change-this-admin-password'
    openai_api_key: str = ''
    gemini_api_key: str = ''
    openai_text_model: str = 'gpt-5-mini'
    # Reasoning models spend part of max_output_tokens on hidden reasoning tokens.
    # Keep the thinking short for formatting-style work; set empty to not send it.
    openai_reasoning_effort: str = 'low'
    openai_image_model: str = 'gpt-image-1'
    openai_text_models: str = 'gpt-5-mini,gpt-5,gpt-4.1-mini,gpt-4.1,gpt-4o-mini,gpt-4o'
    openai_image_models: str = 'gpt-image-2,gpt-image-1,gpt-image-1-mini'
    gemini_image_models: str = 'gemini-3.1-flash-image-preview,gemini-2.5-flash-image,gemini-3-pro-image-preview'
    text_pricing_json: str = json.dumps(DEFAULT_TEXT_PRICING)
    image_pricing_json: str = json.dumps(DEFAULT_IMAGE_PRICING)
    media_dir: str = '/app/media'
    # 'transitional' serves unsigned /media URLs with a warning (old artifacts keep
    # working); 'strict' refuses them. Flip to strict once logs run quiet.
    media_signing: str = 'transitional'
    # GitHub OAuth (порожньо = кнопка входу через GitHub вимкнена).
    github_client_id: str = ''
    github_client_secret: str = ''
    # Явний callback, коли авто-визначення не годиться (TLS за Caddy тощо).
    github_callback_url: str = ''
    # 'shared' (усі редагують усе) або 'owner' (змінює лише власник або admin).
    project_ownership: str = 'shared'
    request_timeout_seconds: int = 75
    # Watchdog: a project stuck in processing/queued longer than this is failed.
    stuck_project_minutes: int = 45
    # Hard daily cap on NEW paid work, USD. 0 disables. Running work finishes.
    daily_budget_usd: float = 25.0
    # Optional failure alerts. Telegram: token + chat id. Webhook: any URL that
    # accepts a JSON POST {"text": ...}. Empty values disable alerts silently.
    telegram_bot_token: str = ''
    telegram_chat_id: str = ''
    alert_webhook_url: str = ''

    def insecure_secrets(self) -> list[str]:
        """Secrets that must be fixed before the API may serve anyone.

        POSTGRES_PASSWORD is deliberately not fatal: Postgres only reads it when the
        data volume is first initialised, so editing .env on an existing deployment
        does not change it and refusing to boot would strand the operator. It is
        warned about instead - see warn_secrets().
        """
        problems = []
        if self.jwt_secret == SHIPPED_DEFAULTS['jwt_secret']:
            problems.append('JWT_SECRET все ще має значення з репозиторію')
        elif len(self.jwt_secret) < 32:
            problems.append('JWT_SECRET коротший за 32 символи')
        if self.admin_password == SHIPPED_DEFAULTS['admin_password']:
            problems.append('ADMIN_PASSWORD все ще має значення з репозиторію')
        elif len(self.admin_password) < 12:
            problems.append('ADMIN_PASSWORD коротший за 12 символів')
        return problems

    def warn_secrets(self) -> list[str]:
        if self.postgres_password == SHIPPED_DEFAULTS['postgres_password']:
            return ['POSTGRES_PASSWORD має значення з репозиторію. Postgres читає його лише під час першої ініціалізації тому, щоб змінити пароль на наявній базі, потрібен ALTER USER, а не правка .env']
        return []

    @property
    def text_models(self):
        return [x.strip() for x in self.openai_text_models.split(',') if x.strip()]

    @property
    def image_models(self):
        return [x.strip() for x in self.openai_image_models.split(',') if x.strip()]

    @property
    def gemini_models(self):
        return [x.strip() for x in self.gemini_image_models.split(',') if x.strip()]

    @property
    def text_pricing(self):
        try:
            loaded = json.loads(self.text_pricing_json)
            return loaded if isinstance(loaded, dict) else DEFAULT_TEXT_PRICING
        except Exception:
            return DEFAULT_TEXT_PRICING

    @property
    def image_pricing(self):
        try:
            loaded = json.loads(self.image_pricing_json)
            return loaded if isinstance(loaded, dict) else DEFAULT_IMAGE_PRICING
        except Exception:
            return DEFAULT_IMAGE_PRICING


settings = Settings()

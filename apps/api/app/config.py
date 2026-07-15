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
    openai_text_model: str = 'gpt-5-mini'
    # Reasoning models spend part of max_output_tokens on hidden reasoning tokens.
    # Keep the thinking short for formatting-style work; set empty to not send it.
    openai_reasoning_effort: str = 'low'
    openai_image_model: str = 'gpt-image-1'
    openai_text_models: str = 'gpt-5-mini,gpt-5,gpt-4.1-mini,gpt-4.1,gpt-4o-mini,gpt-4o'
    openai_image_models: str = 'gpt-image-2,gpt-image-1,gpt-image-1-mini'
    text_pricing_json: str = json.dumps(DEFAULT_TEXT_PRICING)
    image_pricing_json: str = json.dumps(DEFAULT_IMAGE_PRICING)
    media_dir: str = '/app/media'
    request_timeout_seconds: int = 75

    @property
    def text_models(self):
        return [x.strip() for x in self.openai_text_models.split(',') if x.strip()]

    @property
    def image_models(self):
        return [x.strip() for x in self.openai_image_models.split(',') if x.strip()]

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

"""Configuration from the environment (and the repository's .env file in local development)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_REPO_ROOT_ENV, extra="ignore")

    supabase_url: str = ""
    database_url: str = ""
    supabase_secret_key: str = ""
    voyage_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    # "provider:model"; chosen from measurements in ADR 0010.
    answer_model: str = "groq:openai/gpt-oss-120b"
    fallback_answer_model: str = "gemini:gemini-3.5-flash-lite"
    # Judges faithfulness in the Eval Set (#46): never the answer model judging itself.
    judge_model: str = "gemini:gemini-3.5-flash-lite"
    # Below this similarity of the best passage, a question is declined without asking the
    # answer model (#43). Chosen on the Eval Set (#46, evals/README.md): at 0.68, 13 of 14
    # unanswerable questions are declined here and all 36 answerable ones reach the model;
    # the model declines the rest itself.
    decline_below_similarity: float = 0.68

    @property
    def auth_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.auth_issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()

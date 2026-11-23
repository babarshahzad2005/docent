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
    # Tried in order when the answer model fails before writing (ADR 0010): Qwen has its own
    # Groq rate limit, answers in under a second, and follows the citation format; Gemini covers
    # Groq being down, at 5 s or more.
    fallback_answer_model: str = "groq:qwen/qwen3.8-27b,gemini:gemini-3.5-flash-lite"
    # Judges faithfulness in the Eval Set (#46): never the answer model judging itself.
    judge_model: str = "gemini:gemini-3.5-flash-lite"
    # Below this similarity of the best passage, a question is declined without asking the
    # answer model (#43). Chosen on the Eval Set (#46, evals/README.md): at 0.68, all 14
    # unanswerable questions are declined here and all 36 answerable ones reach the model
    # (the lowest scores 0.686); the model can still decline what gets through.
    decline_below_similarity: float = 0.68
    # Visitors' questions to Public Collections (#94): per network address each hour, and all
    # Visitors together each day, keeping most of the free model quota for signed-in Users.
    visitor_questions_per_hour: int = 20
    visitor_questions_per_day: int = 200
    # Keys the hash of Visitors' network addresses; derived from supabase_secret_key if unset.
    visitor_hash_key: str = ""
    # Sites whose pages may call the API from the browser: a Visitor's questions go straight
    # to it, so the limits count the Visitor's own address (limits.client_address).
    # Comma-separated; and a pattern for the web app's preview deployments.
    web_origins: str = "https://docent-tan.vercel.app,http://localhost:3000"
    web_origin_pattern: str = (
        r"https://docent-[a-z0-9-]+-babarshahzad2005-8329s-projects\.vercel\.app"
    )

    @property
    def auth_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.auth_issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()

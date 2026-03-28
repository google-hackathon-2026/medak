# backend/config.py
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    google_api_key: str = ""
    google_cloud_project: str = "proud-quasar-310818"
    google_cloud_location: str = "us-central1"
    redis_url: str = "redis://localhost:6379"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    emergency_number: str = ""
    triage_timeout_seconds: int = 10
    confidence_threshold: float = 0.85
    reconnect_max_attempts: int = 3
    backend_base_url: str = "http://localhost:8080"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("emergency_number")
    @classmethod
    def reject_real_emergency_numbers(cls, v: str) -> str:
        normalized = v.strip().lstrip("+0")
        if normalized in ("112", "194"):
            raise ValueError(
                "Cannot use real emergency numbers (112/194). "
                "Use a team member's phone for demo."
            )
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


def create_genai_client():
    """Create a Gemini client using API key or Vertex AI depending on config."""
    from google import genai

    settings = get_settings()
    if settings.google_api_key:
        return genai.Client(api_key=settings.google_api_key)
    return genai.Client(
        vertexai=True,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
    )

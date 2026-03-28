# backend/config.py
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    google_api_key: str = ""
    redis_url: str = "redis://localhost:6379"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    emergency_number: str = ""
    triage_timeout_seconds: int = 10
    confidence_threshold: float = 0.85
    reconnect_max_attempts: int = 3

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

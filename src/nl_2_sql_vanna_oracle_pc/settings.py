from dataclasses import dataclass, field
from os import getenv

from dotenv import load_dotenv

from .schema_context import ALLOWED_COLUMNS


load_dotenv()


def parse_csv_env(name: str) -> set[str]:
    return {
        value.strip().upper()
        for value in getenv(name, "").split(",")
        if value.strip()
    }


def default_allowed_columns() -> set[str]:
    configured = parse_csv_env("ALLOWED_COLUMNS")
    return configured or set(ALLOWED_COLUMNS)


def build_oracle_dsn() -> str:
    explicit = getenv("ORACLE_DSN", "").strip()
    if explicit:
        return explicit

    host = getenv("ORACLE_HOST", "localhost")
    port = getenv("ORACLE_PORT", "1521")
    service = getenv("ORACLE_SERVICE_NAME", getenv("ORACLE_SID", "ORCL"))
    return f"{host}:{port}/{service}"


def build_ollama_host() -> str:
    """Return Ollama base URL without embedded credentials."""
    host = getenv("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
    if "@" not in host:
        return host

    scheme, _, rest = host.partition("://")
    if not rest:
        return host

    _, _, host_without_auth = rest.partition("@")
    if scheme:
        return f"{scheme}://{host_without_auth}"
    return host_without_auth


@dataclass(frozen=True)
class Settings:
    ollama_model: str = getenv("OLLAMA_MODEL")
    ollama_host: str = field(default_factory=build_ollama_host)
    ollama_basic_auth_user: str = getenv("OLLAMA_BASIC_AUTH_USER", "").strip()
    ollama_basic_auth_password: str = getenv("OLLAMA_BASIC_AUTH_PASSWORD", "")

    oracle_user: str = getenv("ORACLE_USER", "")
    oracle_password: str = getenv("ORACLE_PASSWORD", "")
    oracle_dsn: str = field(default_factory=build_oracle_dsn)

    chroma_collection_name: str = getenv("CHROMA_COLLECTION_NAME")
    chroma_persist_directory: str = getenv("CHROMA_PERSIST_DIRECTORY")

    allowed_tables: set[str] = field(default_factory=lambda: parse_csv_env("ALLOWED_TABLES"))
    allowed_columns: set[str] = field(default_factory=default_allowed_columns)

    speech_recognition_lang: str = getenv("SPEECH_RECOGNITION_LANG", "vi-VN")

    app_basic_auth_user: str = getenv("APP_BASIC_AUTH_USER", "").strip()
    app_basic_auth_password: str = getenv("APP_BASIC_AUTH_PASSWORD", "")

    @property
    def basic_auth_enabled(self) -> bool:
        return bool(self.app_basic_auth_user and self.app_basic_auth_password)

    @property
    def ollama_basic_auth_enabled(self) -> bool:
        return bool(self.ollama_basic_auth_user and self.ollama_basic_auth_password)


settings = Settings()

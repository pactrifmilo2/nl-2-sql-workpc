from __future__ import annotations

import base64

from vanna.integrations.ollama import OllamaLlmService

from .settings import Settings


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def create_llm_service(settings: Settings) -> OllamaLlmService:
    headers = None
    if settings.ollama_basic_auth_enabled:
        headers = _basic_auth_header(
            settings.ollama_basic_auth_user,
            settings.ollama_basic_auth_password,
        )

    service = OllamaLlmService(
        model=settings.ollama_model,
        host=settings.ollama_host,
        temperature=0.2,
    )

    if headers:
        import ollama

        service._client = ollama.Client(
            host=settings.ollama_host,
            headers=headers,
            timeout=service.timeout,
        )

    return service

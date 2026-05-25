from vanna.integrations.ollama import OllamaLlmService

from .settings import Settings


def create_llm_service(settings: Settings) -> OllamaLlmService:
    return OllamaLlmService(
        model=settings.ollama_model,
        host=settings.ollama_host,
        temperature=0.2,
    )


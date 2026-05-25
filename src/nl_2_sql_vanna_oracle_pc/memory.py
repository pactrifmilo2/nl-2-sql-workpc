from vanna.integrations.chromadb import ChromaAgentMemory

from .settings import Settings


class ResilientChromaAgentMemory(ChromaAgentMemory):
    def _get_collection(self):
        if self._collection is None:
            client = self._get_client()
            embedding_func = self._get_embedding_function()
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=embedding_func,
                metadata={"description": "Tool usage memories for learning"},
            )

        return self._collection

    def ensure_collection(self) -> None:
        self._get_collection()

    async def search_similar_usage(self, *args, **kwargs):
        try:
            return await super().search_similar_usage(*args, **kwargs)
        except Exception as exc:
            if "does not exist" not in str(exc).lower():
                raise

            self._collection = None
            self.ensure_collection()
            return []

    async def search_text_memories(self, *args, **kwargs):
        try:
            return await super().search_text_memories(*args, **kwargs)
        except Exception as exc:
            if "does not exist" not in str(exc).lower():
                raise

            self._collection = None
            self.ensure_collection()
            return []


def create_agent_memory(settings: Settings) -> ResilientChromaAgentMemory:
    memory = ResilientChromaAgentMemory(
        collection_name=settings.chroma_collection_name,
        persist_directory=settings.chroma_persist_directory,
    )
    memory.ensure_collection()
    return memory


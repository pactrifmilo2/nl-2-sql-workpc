import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from vanna.integrations.chromadb import ChromaAgentMemory

from .settings import Settings

logger = logging.getLogger(__name__)


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

    async def upsert_tool_memory(
        self,
        *,
        memory_id: str,
        question: str,
        tool_name: str,
        args: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Idempotently sync a canonical tool memory into Chroma."""

        def _upsert() -> None:
            timestamp = datetime.now(timezone.utc).isoformat()
            self._get_collection().upsert(
                ids=[memory_id],
                documents=[question],
                metadatas=[
                    {
                        "question": question,
                        "tool_name": tool_name,
                        "args_json": json.dumps(args, ensure_ascii=False),
                        "timestamp": timestamp,
                        "success": True,
                        "metadata_json": json.dumps(
                            metadata or {}, ensure_ascii=False
                        ),
                    }
                ],
            )

        await asyncio.get_running_loop().run_in_executor(self._executor, _upsert)

    async def upsert_text_memory(
        self,
        *,
        memory_id: str,
        content: str,
    ) -> None:
        """Idempotently sync a canonical text memory into Chroma."""

        def _upsert() -> None:
            self._get_collection().upsert(
                ids=[memory_id],
                documents=[content],
                metadatas=[
                    {
                        "content": content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "is_text_memory": True,
                    }
                ],
            )

        await asyncio.get_running_loop().run_in_executor(self._executor, _upsert)

    async def remove_duplicate_tool_memories(
        self,
        *,
        keep_memory_id: str,
        question: str,
        tool_name: str,
        args: dict[str, Any],
    ) -> int:
        """Remove legacy random-ID copies of an exact canonical tool memory."""

        def _remove() -> int:
            results = self._get_collection().get()
            duplicate_ids: list[str] = []
            expected_args = self._normalized_args(args)
            for memory_id, metadata in zip(
                results.get("ids") or [], results.get("metadatas") or []
            ):
                if memory_id == keep_memory_id or metadata.get("is_text_memory"):
                    continue
                try:
                    stored_args = json.loads(metadata.get("args_json", "{}"))
                except json.JSONDecodeError:
                    continue
                if (
                    metadata.get("question") == question
                    and metadata.get("tool_name") == tool_name
                    and self._normalized_args(stored_args) == expected_args
                ):
                    duplicate_ids.append(memory_id)
            if duplicate_ids:
                self._get_collection().delete(ids=duplicate_ids)
            return len(duplicate_ids)

        return await asyncio.get_running_loop().run_in_executor(self._executor, _remove)

    async def remove_duplicate_text_memories(
        self, *, keep_memory_id: str, content: str
    ) -> int:
        """Remove legacy random-ID copies of an exact canonical text memory."""

        def _remove() -> int:
            results = self._get_collection().get()
            duplicate_ids = [
                memory_id
                for memory_id, metadata in zip(
                    results.get("ids") or [], results.get("metadatas") or []
                )
                if memory_id != keep_memory_id
                and metadata.get("is_text_memory")
                and metadata.get("content") == content
            ]
            if duplicate_ids:
                self._get_collection().delete(ids=duplicate_ids)
            return len(duplicate_ids)

        return await asyncio.get_running_loop().run_in_executor(self._executor, _remove)

    @staticmethod
    def _normalized_args(args: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(args)
        if isinstance(normalized.get("sql"), str):
            normalized["sql"] = " ".join(normalized["sql"].split())
        return normalized

    async def search_similar_usage(self, *args, **kwargs):
        try:
            return await super().search_similar_usage(*args, **kwargs)
        except Exception as exc:
            if "does not exist" not in str(exc).lower():
                raise

            logger.warning("Chroma collection missing during tool search; reinitializing: %s", exc)
            self._collection = None
            self.ensure_collection()
            return []

    async def search_text_memories(self, *args, **kwargs):
        try:
            return await super().search_text_memories(*args, **kwargs)
        except Exception as exc:
            if "does not exist" not in str(exc).lower():
                raise

            logger.warning("Chroma collection missing during text search; reinitializing: %s", exc)
            self._collection = None
            self.ensure_collection()
            return []


def create_agent_memory(settings: Settings) -> ResilientChromaAgentMemory:
    memory = ResilientChromaAgentMemory(
        collection_name=settings.chroma_collection_name,
        persist_directory=settings.chroma_persist_directory,
    )
    memory.ensure_collection()
    logger.debug(
        "Agent memory ready: collection=%s persist_dir=%s",
        settings.chroma_collection_name,
        settings.chroma_persist_directory,
    )
    return memory


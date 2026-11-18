"""One switch for the model provider.

LLM_PROVIDER=bedrock  -> Amazon Bedrock Converse API (uses the ECS task role, no API key)
LLM_PROVIDER=openai   -> any OpenAI-compatible endpoint: OpenAI itself, or Bedrock's
                         OpenAI-compatible "Mantle" endpoint. The OpenAI SDK reads
                         OPENAI_API_KEY, OPENAI_BASE_URL and OPENAI_PROJECT_ID from the environment.

EMBEDDINGS_PROVIDER (defaults to LLM_PROVIDER):
  bedrock | openai    -> hosted embedding model
  local               -> a hashing embedder in pure Python/NumPy. No API call, so RAG keeps
                         working on endpoints that only serve chat models.
"""

from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache

import numpy as np
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "bedrock").lower()


def embeddings_provider() -> str:
    return os.getenv("EMBEDDINGS_PROVIDER", provider()).lower()


def model_name() -> str:
    if provider() == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-lite-v1:0")


@lru_cache(maxsize=1)
def get_chat_model() -> BaseChatModel:
    if provider() == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model_name(), temperature=0, timeout=60, max_retries=2)

    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(
        model=model_name(),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        temperature=0,
        max_tokens=1024,
    )


class HashingEmbeddings(Embeddings):
    """Word and character-trigram features hashed into a fixed-size vector.

    Lexical, not semantic, but strong enough to rank a small notebook of tips that name
    their places and months. Deterministic and free.
    """

    def __init__(self, dims: int = 1024):
        self.dims = dims

    def _features(self, text: str) -> list[str]:
        words = re.findall(r"[a-z0-9]+", text.lower())
        grams = [w[i:i + 3] for w in words if len(w) > 3 for i in range(len(w) - 2)]
        return words + grams

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dims, dtype=np.float32)
        for f in self._features(text):
            h = int(hashlib.md5(f.encode()).hexdigest(), 16)
            v[h % self.dims] += 1.0 if (h >> 64) & 1 else -1.0
        n = np.linalg.norm(v)
        return (v / n if n else v).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    choice = embeddings_provider()
    if choice == "local":
        return HashingEmbeddings()
    if choice == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"))

    from langchain_aws import BedrockEmbeddings

    return BedrockEmbeddings(
        model_id=os.getenv("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0"),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )

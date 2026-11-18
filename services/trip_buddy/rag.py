"""The travel notebook (RAG). 13 tips, embedded once at startup, searched by cosine similarity.

With so few documents a NumPy matrix is the right-sized vector index: no extra service to run.
Swap in OpenSearch Serverless or S3 Vectors when the notebook grows to thousands of tips.
"""

from __future__ import annotations

import numpy as np
from langchain_core.embeddings import Embeddings

KB = [
    ("trip-cost", "Trip cost per person = travel + stay share + daily spend x nights."),
    ("rooms", "One room fits 2 people, so rooms needed = people / 2, rounded up. Stay share = rooms x room price x nights / people."),
    ("buffer", "Keep a 10% buffer on top of the total for surprises like a cab surge or a missed bus."),
    ("splitting", "Split shared costs (stay, cabs, fuel) equally. Personal shopping is never split."),
    ("beach", "Beach trips (Goa, Gokarna, Pondicherry): best November-February. In the monsoon (June-September) many beach shacks and water sports close."),
    ("hills", "Hill trips (Coorg, Ooty, Manali): best March-June and October. Avoid July-August: heavy rain and landslides block hill roads. Carry a jacket even in summer."),
    ("heritage", "Heritage trips (Hampi, Jaipur): best October-March. April-May afternoons cross 40C, so explore early in the morning."),
    ("adventure", "Adventure trips (Rishikesh, Dandeli): river rafting runs October-June and closes in the monsoon. Use licensed operators and always wear a life jacket."),
    ("book-early", "Book trains and flights 30-60 days early; prices often double in the last week."),
    ("weekdays", "Weekday stays are often 20-30% cheaper than weekends."),
    ("long-weekend", "Long weekends and New Year push Goa prices up sharply; book early or pick Gokarna instead."),
    ("overnight", "Overnight buses and trains save the cost of one night's stay."),
    ("big-group", "Groups bigger than 6: a villa or homestay is usually cheaper than many hotel rooms."),
]


class TravelNotebook:
    def __init__(self, embeddings: Embeddings, docs: list[tuple[str, str]] = KB):
        self.embeddings = embeddings
        self.ids = [i for i, _ in docs]
        self.texts = [t for _, t in docs]
        self._matrix: np.ndarray | None = None

    def _ensure_index(self) -> np.ndarray:
        if self._matrix is None:
            m = np.asarray(self.embeddings.embed_documents(self.texts), dtype=np.float32)
            self._matrix = m / np.linalg.norm(m, axis=1, keepdims=True)
        return self._matrix

    def search(self, query: str, n: int = 3) -> list[tuple[str, str, float]]:
        matrix = self._ensure_index()
        q = np.asarray(self.embeddings.embed_query(query), dtype=np.float32)
        q = q / np.linalg.norm(q)
        scores = matrix @ q
        top = np.argsort(-scores)[:n]
        return [(self.ids[i], self.texts[i], float(scores[i])) for i in top]

    def context(self, query: str, n: int = 3) -> str:
        return "\n".join(f"- {text}" for _, text, _ in self.search(query, n))

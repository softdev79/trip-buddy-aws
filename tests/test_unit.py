"""Fast tests that need no LLM, no network and no AWS account. Run in CI on every push."""

import hashlib

import pytest
from langchain_core.embeddings import Embeddings

from destinations import DestinationStore
from rag import TravelNotebook
from sessions import KEEP_LAST, SessionStore
from tripbuddy_shared.trip_math import compute_trip_cost


# ------------------------------------------------------------------ trip maths
def test_goa_four_friends_three_nights():
    # travel 2800 + stay 2 rooms * 3000 * 3 / 4 = 4500 + food 1500 * 3 = 4500
    r = compute_trip_cost(2800, 3000, 1500, people=4, nights=3, budget_per_person=12000)
    assert r == {"rooms_needed": 2, "stay_share_per_person": 4500.0, "food_and_fun_per_person": 4500.0,
                 "total_per_person": 11800.0, "within_budget": True, "money_left_per_person": 200.0}


def test_odd_group_rounds_rooms_up():
    r = compute_trip_cost(900, 1500, 800, people=5, nights=2)
    assert r["rooms_needed"] == 3
    assert r["stay_share_per_person"] == 1800.0
    assert "within_budget" not in r


def test_rejects_zero_people():
    with pytest.raises(ValueError):
        compute_trip_cost(1, 1, 1, people=0, nights=1)


# ------------------------------------------------------------------ destinations
def test_lookup_by_id_and_name():
    store = DestinationStore(table_name="")
    assert store.backend == "memory"
    assert store.get("pondy")["name"] == "Pondicherry"
    assert store.get("Pondicherry")["place_id"] == "PONDY"
    assert store.get("Atlantis") is None


def test_list_summary_sorted_by_type():
    rows = DestinationStore(table_name="").list_summary()
    assert len(rows) == 10
    assert set(rows[0]) == {"place_id", "name", "trip_type", "best_months"}
    assert [r["trip_type"] for r in rows] == sorted(r["trip_type"] for r in rows)


# ------------------------------------------------------------------ RAG
class KeywordEmbeddings(Embeddings):
    """Deterministic fake: a bag-of-words hashed into 64 dims. Good enough to test ranking."""

    def _vec(self, text):
        v = [0.0] * 64
        for word in text.lower().replace(",", " ").replace(".", " ").split():
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1.0
        return v

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


def test_rag_finds_the_hills_tip():
    nb = TravelNotebook(KeywordEmbeddings())
    ids = [doc_id for doc_id, _, _ in nb.search("hill trips landslides rain jacket", n=3)]
    assert ids[0] == "hills"


def test_rag_context_is_bullets():
    ctx = TravelNotebook(KeywordEmbeddings()).context("room price people", n=2)
    assert ctx.count("\n") == 1 and ctx.startswith("- ")


# ------------------------------------------------------------------ sessions
def test_session_memory_is_trimmed():
    store = SessionStore(table_name="")
    for i in range(10):
        store.append("s1", f"q{i}", f"a{i}")
    history = store.load("s1")
    assert len(history) == KEEP_LAST
    assert history[-1] == {"role": "assistant", "content": "a9"}
    store.clear("s1")
    assert store.load("s1") == []


def test_local_embeddings_rank_the_right_tips():
    from tripbuddy_shared.llm import HashingEmbeddings

    nb = TravelNotebook(HashingEmbeddings())
    assert nb.search("Is Manali a good idea in July?", n=1)[0][0] == "hills"
    assert nb.search("Can we go rafting in Rishikesh?", n=1)[0][0] == "adventure"
    assert "rooms" in [i for i, _, _ in nb.search("how many rooms for 5 people", n=2)]

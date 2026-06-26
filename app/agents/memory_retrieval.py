from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.domain.models import AgentMemorySnapshot


@dataclass(frozen=True)
class MemorySearchQuery:
    anchors: frozenset[str]
    text_tokens: frozenset[str]
    semantic_tokens: frozenset[str] = field(default_factory=frozenset)
    target_id: str | None = None


@dataclass(frozen=True)
class MemorySearchScore:
    total: float
    structured: float
    keyword: float
    embedding: float
    rerank: float
    recency: float
    reinforcement: float
    salience: float
    confidence: float
    updated_at: str
    memory_id: str
    has_relevance: bool

    @property
    def sort_key(self) -> tuple[float, float, float, float, float, str, str]:
        return (
            self.total,
            self.structured,
            self.keyword,
            self.reinforcement,
            self.confidence,
            self.updated_at,
            self.memory_id,
        )


@dataclass(frozen=True)
class MemorySearchResult:
    snapshot: AgentMemorySnapshot
    score: MemorySearchScore


@dataclass(frozen=True)
class MemoryHardFilter:
    name: str
    predicate: Callable[[AgentMemorySnapshot], bool]


class EmbeddingScorer(Protocol):
    def score(
        self,
        *,
        query: MemorySearchQuery,
        snapshot: AgentMemorySnapshot,
    ) -> float:
        """Return a deterministic relevance score for one candidate snapshot."""


class MemoryReranker(Protocol):
    def rerank(
        self,
        *,
        query: MemorySearchQuery,
        results: Sequence[MemorySearchResult],
    ) -> Sequence[MemorySearchResult]:
        """Return the same candidates in a refined order or with adjusted scores."""


class NoopEmbeddingScorer:
    def score(
        self,
        *,
        query: MemorySearchQuery,
        snapshot: AgentMemorySnapshot,
    ) -> float:
        _ = query, snapshot
        return 0.0


class NoopMemoryReranker:
    def rerank(
        self,
        *,
        query: MemorySearchQuery,
        results: Sequence[MemorySearchResult],
    ) -> Sequence[MemorySearchResult]:
        _ = query
        return results


class LocalSemanticEmbeddingScorer:
    """Deterministic first-stage semantic scorer for already-filtered candidates.

    This is intentionally not a vector store. It never fetches candidates and must
    only run inside the retrieval pipeline after scope/layer/visibility/phase and
    forbidden-fact hard filters have already accepted a snapshot.
    """

    def __init__(
        self,
        concept_aliases: Mapping[str, Iterable[str]],
        *,
        tokenizer: Callable[[str], set[str]],
        haystack_builder: Callable[[AgentMemorySnapshot], str],
        cap: float = 1.25,
        concept_weight: float = 1.0,
        overlap_weight: float = 0.08,
        weak_tokens: Iterable[str] = (),
    ) -> None:
        self._tokenizer = tokenizer
        self._haystack_builder = haystack_builder
        self._cap = cap
        self._concept_weight = concept_weight
        self._overlap_weight = overlap_weight
        self._weak_tokens = frozenset(str(token) for token in weak_tokens)
        self._concept_tokens = _compile_concept_tokens(
            concept_aliases,
            tokenizer=tokenizer,
        )

    def score(
        self,
        *,
        query: MemorySearchQuery,
        snapshot: AgentMemorySnapshot,
    ) -> float:
        if not self._concept_tokens:
            return 0.0
        anchored_concepts = self._anchored_concepts(query)
        if not anchored_concepts:
            return 0.0
        query_tokens = self._query_tokens(query)
        if not query_tokens:
            return 0.0
        snapshot_tokens = self._tokenizer(self._haystack_builder(snapshot))
        if not snapshot_tokens:
            return 0.0

        score = 0.0
        for concept_id, alias_tokens in self._concept_tokens.items():
            if concept_id not in anchored_concepts:
                continue
            query_overlap = query_tokens & alias_tokens
            if not _has_distinctive_overlap(query_overlap, self._weak_tokens):
                continue
            snapshot_overlap = snapshot_tokens & alias_tokens
            if not _has_distinctive_overlap(snapshot_overlap, self._weak_tokens):
                continue
            score += self._concept_weight
            score += min(len(query_overlap | snapshot_overlap), 4) * self._overlap_weight
        return min(score, self._cap)

    def _query_tokens(self, query: MemorySearchQuery) -> set[str]:
        tokens = set(query.text_tokens)
        tokens.update(query.semantic_tokens)
        for anchor in query.anchors:
            tokens.update(self._tokenizer(anchor))
        return tokens

    def _anchored_concepts(self, query: MemorySearchQuery) -> set[str]:
        return {str(anchor) for anchor in query.anchors} & set(self._concept_tokens)


class LocalBM25KeywordScorer:
    def __init__(
        self,
        snapshots: Iterable[AgentMemorySnapshot],
        *,
        tokenizer: Callable[[str], set[str]],
        haystack_builder: Callable[[AgentMemorySnapshot], str],
        cap: float,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> None:
        self._tokenizer = tokenizer
        self._haystack_builder = haystack_builder
        self._cap = cap
        self._k1 = k1
        self._b = b
        self._documents: dict[str, Counter[str]] = {}
        self._doc_lengths: dict[str, int] = {}
        document_frequency: Counter[str] = Counter()
        for snapshot in snapshots:
            terms = Counter(tokenizer(haystack_builder(snapshot)))
            self._documents[snapshot.memory_id] = terms
            doc_length = sum(terms.values())
            self._doc_lengths[snapshot.memory_id] = doc_length
            for term in terms:
                document_frequency[term] += 1
        self._document_frequency = document_frequency
        self._document_count = max(1, len(self._documents))
        total_length = sum(self._doc_lengths.values())
        self._average_doc_length = total_length / self._document_count if total_length else 1.0

    def score(
        self,
        *,
        query: MemorySearchQuery,
        snapshot: AgentMemorySnapshot,
    ) -> float:
        if not query.text_tokens:
            return 0.0
        document_terms = self._documents.get(snapshot.memory_id, Counter())
        if not document_terms:
            return 0.0
        doc_length = max(1, self._doc_lengths.get(snapshot.memory_id, 1))
        score = 0.0
        for token in query.text_tokens:
            frequency = document_terms.get(token, 0)
            if frequency <= 0:
                continue
            document_frequency = self._document_frequency.get(token, 0)
            idf = math.log(
                1
                + (
                    self._document_count - document_frequency + 0.5
                )
                / (document_frequency + 0.5)
            )
            denominator = frequency + self._k1 * (
                1 - self._b + self._b * doc_length / self._average_doc_length
            )
            score += idf * (frequency * (self._k1 + 1) / denominator)
        return min(score, self._cap)


class MemoryRetrievalPipeline:
    def __init__(
        self,
        *,
        structured_scorer: Callable[[AgentMemorySnapshot, MemorySearchQuery], float],
        keyword_scorer_factory: Callable[
            [Sequence[AgentMemorySnapshot]],
            LocalBM25KeywordScorer,
        ],
        recency_scorer: Callable[[AgentMemorySnapshot], float],
        reinforcement_scorer: Callable[[AgentMemorySnapshot], float],
        embedding_scorer: EmbeddingScorer | None = None,
        reranker: MemoryReranker | None = None,
    ) -> None:
        self._structured_scorer = structured_scorer
        self._keyword_scorer_factory = keyword_scorer_factory
        self._recency_scorer = recency_scorer
        self._reinforcement_scorer = reinforcement_scorer
        self._embedding_scorer = embedding_scorer or NoopEmbeddingScorer()
        self._reranker = reranker or NoopMemoryReranker()

    def search(
        self,
        *,
        query: MemorySearchQuery,
        snapshots: Sequence[AgentMemorySnapshot],
        hard_filters: Sequence[MemoryHardFilter],
    ) -> list[MemorySearchResult]:
        candidates = self._apply_hard_filters(snapshots, hard_filters)
        keyword_scorer = self._keyword_scorer_factory(candidates)
        results = [
            self._score_candidate(
                query=query,
                snapshot=snapshot,
                keyword_scorer=keyword_scorer,
            )
            for snapshot in candidates
        ]
        relevant_results = [result for result in results if result.score.has_relevance]
        relevant_results.sort(key=lambda result: result.score.sort_key, reverse=True)
        reranked = self._reranker.rerank(
            query=query,
            results=relevant_results,
        )
        return list(reranked)

    def _apply_hard_filters(
        self,
        snapshots: Sequence[AgentMemorySnapshot],
        hard_filters: Sequence[MemoryHardFilter],
    ) -> list[AgentMemorySnapshot]:
        return [
            snapshot
            for snapshot in snapshots
            if all(hard_filter.predicate(snapshot) for hard_filter in hard_filters)
        ]

    def _score_candidate(
        self,
        *,
        query: MemorySearchQuery,
        snapshot: AgentMemorySnapshot,
        keyword_scorer: LocalBM25KeywordScorer,
    ) -> MemorySearchResult:
        structured = self._structured_scorer(snapshot, query)
        keyword = keyword_scorer.score(query=query, snapshot=snapshot)
        embedding = self._embedding_scorer.score(query=query, snapshot=snapshot)
        has_relevance = structured > 0 or keyword > 0 or embedding > 0
        recency = self._recency_scorer(snapshot) if has_relevance else 0.0
        reinforcement = self._reinforcement_scorer(snapshot) if has_relevance else 0.0
        confidence = snapshot.confidence * 0.15 if has_relevance else 0.0
        total = (
            structured
            + keyword
            + embedding
            + recency
            + reinforcement
            + confidence
        )
        score = MemorySearchScore(
            total=total if has_relevance else 0.0,
            structured=structured,
            keyword=keyword,
            embedding=embedding,
            rerank=0.0,
            recency=recency,
            reinforcement=reinforcement,
            salience=snapshot.salience,
            confidence=snapshot.confidence,
            updated_at=snapshot.updated_at or snapshot.created_at or "",
            memory_id=snapshot.memory_id,
            has_relevance=has_relevance,
        )
        return MemorySearchResult(snapshot=snapshot, score=score)


def _compile_concept_tokens(
    concept_aliases: Mapping[str, Iterable[str]],
    *,
    tokenizer: Callable[[str], set[str]],
) -> dict[str, frozenset[str]]:
    compiled: dict[str, frozenset[str]] = {}
    for concept, aliases in concept_aliases.items():
        tokens = set(tokenizer(str(concept)))
        for alias in aliases:
            tokens.update(tokenizer(str(alias)))
        if tokens:
            compiled[str(concept)] = frozenset(tokens)
    return compiled


def _has_distinctive_overlap(tokens: set[str], weak_tokens: frozenset[str]) -> bool:
    return any(token not in weak_tokens for token in tokens)

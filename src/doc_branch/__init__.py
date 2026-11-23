"""Phase 4 Document Branch: hybrid pgvector/FTS RRF search, metadata filters, reranker, 1-retry HyDE, and CRAG."""
from src.doc_branch.evaluator import evaluate_doc_recall_ablation
from src.doc_branch.models import DocumentSearchResult, MetadataFilter, Passage
from src.doc_branch.reranker import Reranker
from src.doc_branch.retriever import hybrid_search_chunks, retrieve_passages, search_documents

__all__ = [
    "DocumentSearchResult",
    "MetadataFilter",
    "Passage",
    "Reranker",
    "evaluate_doc_recall_ablation",
    "hybrid_search_chunks",
    "retrieve_passages",
    "search_documents",
]

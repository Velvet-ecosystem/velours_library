"""Velour's shared local-first knowledge library."""
from .catalog import Candidate, EvidenceResult, Library, LibraryItem, SearchResult
from .pack_intake import PackIntakeCandidate, PackIntakeManager
from .packs import KnowledgePackManager

__all__ = [
    "Candidate",
    "EvidenceResult",
    "KnowledgePackManager",
    "Library",
    "LibraryItem",
    "PackIntakeCandidate",
    "PackIntakeManager",
    "SearchResult",
]
__version__ = "0.6.0"

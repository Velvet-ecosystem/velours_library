"""Velour's shared local-first knowledge library."""
from .catalog import Candidate, EvidenceResult, Library, LibraryItem, SearchResult
from .pack_adoption import PackAdoptionManager
from .pack_intake import PackIntakeCandidate, PackIntakeManager
from .pack_lifecycle import PackLifecycleManager
from .packs import KnowledgePackManager

__all__ = [
    "Candidate",
    "EvidenceResult",
    "KnowledgePackManager",
    "Library",
    "LibraryItem",
    "PackAdoptionManager",
    "PackIntakeCandidate",
    "PackIntakeManager",
    "PackLifecycleManager",
    "SearchResult",
]
__version__ = "0.8.0"

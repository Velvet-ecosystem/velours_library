"""Velour's shared local-first knowledge library."""
from .acquisition import (
    AcquisitionError,
    AcquisitionManager,
    AcquisitionRecord,
    SourcePolicy,
    SourceRule,
)
from .catalog import Candidate, EvidenceResult, Library, LibraryItem, SearchResult
from .pack_adoption import PackAdoptionManager
from .pack_intake import PackIntakeCandidate, PackIntakeManager
from .pack_lifecycle import PackLifecycleManager
from .packs import KnowledgePackManager
from .source_provenance import SourceProvenance, SourceProvenanceManager

__all__ = [
    "AcquisitionError",
    "AcquisitionManager",
    "AcquisitionRecord",
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
    "SourcePolicy",
    "SourceProvenance",
    "SourceProvenanceManager",
    "SourceRule",
]
__version__ = "0.10.0"

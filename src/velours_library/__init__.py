"""Velour's shared local-first knowledge library."""
from .acquisition import (
    AcquisitionError,
    AcquisitionManager,
    AcquisitionRecord,
    SourcePolicy,
    SourceRule,
)
from .catalog import Candidate, EvidenceResult, Library, LibraryItem, SearchResult
from .doctor import LibraryDoctor
from .ingest import BulkIngestor, DocumentLibrary, DocumentMetadata, IngestResult
from .pack_adoption import PackAdoptionManager
from .pack_intake import PackIntakeCandidate, PackIntakeManager
from .pack_lifecycle import PackLifecycleManager
from .packs import KnowledgePackManager
from .snapshot import LibrarySnapshotManager
from .source_provenance import SourceProvenance, SourceProvenanceManager
from .zim_shelf import ZimArchive, ZimShelf

__all__ = [
    "AcquisitionError",
    "AcquisitionManager",
    "AcquisitionRecord",
    "BulkIngestor",
    "Candidate",
    "DocumentLibrary",
    "DocumentMetadata",
    "EvidenceResult",
    "IngestResult",
    "KnowledgePackManager",
    "Library",
    "LibraryDoctor",
    "LibraryItem",
    "LibrarySnapshotManager",
    "PackAdoptionManager",
    "PackIntakeCandidate",
    "PackIntakeManager",
    "PackLifecycleManager",
    "SearchResult",
    "SourcePolicy",
    "SourceProvenance",
    "SourceProvenanceManager",
    "SourceRule",
    "ZimArchive",
    "ZimShelf",
]
__version__ = "0.12.0"

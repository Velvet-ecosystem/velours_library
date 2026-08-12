"""Velour's shared local-first knowledge library."""
from .catalog import Candidate, EvidenceResult, Library, LibraryItem, SearchResult
from .packs import KnowledgePackManager

__all__ = ["Candidate", "EvidenceResult", "KnowledgePackManager", "Library", "LibraryItem", "SearchResult"]
__version__ = "0.5.0"

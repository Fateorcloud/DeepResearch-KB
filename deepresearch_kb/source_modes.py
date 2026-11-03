"""Shared request rules for explicit research sources."""
from typing import Literal


SourceMode = Literal["web", "local", "hybrid"]


class SourceModeError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def validate_source_mode(source_mode, knowledge_base_ids, required_source_types=()):
    if source_mode not in {"web", "local", "hybrid"}:
        raise SourceModeError("invalid_source_mode", "Source mode must be web, local, or hybrid")
    if source_mode in {"local", "hybrid"} and not knowledge_base_ids:
        raise SourceModeError(
            "source_mode_requires_knowledge_base", "Local and hybrid modes require at least one knowledge base")
    if source_mode == "web" and knowledge_base_ids:
        raise SourceModeError(
            "web_mode_disallows_knowledge_bases", "Web mode does not accept knowledge bases")
    incompatible = ({"local_import", "web_upload"} if source_mode == "web" else
                    {"external_web"} if source_mode == "local" else set())
    if incompatible.intersection(required_source_types):
        raise SourceModeError(
            "source_mode_source_type_conflict", "Required source types conflict with source mode")

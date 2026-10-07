from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


ScopeType = Literal["device", "role_platform", "platform", "global"]
ApprovalDecision = Literal["approved", "approved_with_changes"]
OperationResult = Literal["success", "failure"]


class SearchDeviceQuirksRequest(BaseModel):
    device_names: List[str] = Field(
        ...,
        description="Canonical Nornir device_name values in the current operation.",
    )
    operation_type: Optional[str] = Field(
        None,
        description="Concrete operation/tool, for example configure_fabric_bulk.",
    )
    intent_class: Optional[str] = Field(
        None,
        description="High-level intent, for example zero_to_hero_fabric or day_n_change.",
    )
    phase: Optional[str] = Field(
        None,
        description="Execution phase, for example underlay, overlay, or dataplane.",
    )
    platforms: Optional[List[str]] = Field(
        None,
        description="Optional platform filters. If omitted, derived from inventory when possible.",
    )
    fabric_roles: Optional[List[str]] = Field(
        None,
        description="Optional fabric role filters. If omitted, derived from inventory when possible.",
    )
    query: Optional[str] = Field(
        None,
        description="Short free-text hint describing the operation focus.",
    )
    limit: int = Field(
        5,
        ge=1,
        le=10,
        description="Maximum number of matching rules to return.",
    )


class ListMemoryEpisodesRequest(BaseModel):
    device_names: Optional[List[str]] = Field(
        None,
        description="Optional canonical Nornir device_name values to filter applicable episodes.",
    )
    device_name: Optional[str] = Field(
        None,
        description="Optional exact target device_name filter.",
    )
    scope: Optional[ScopeType] = None
    platform: Optional[str] = None
    fabric_role: Optional[str] = None
    operation_type: Optional[str] = None
    intent_class: Optional[str] = None
    phase: Optional[str] = None
    tags: Optional[List[str]] = Field(
        None,
        description="Optional tags. Episodes must contain every requested tag.",
    )
    include_invalidated: bool = Field(
        False,
        description="Whether invalidated/superseded episodes should be included.",
    )
    limit: int = Field(
        20,
        ge=1,
        le=100,
        description="Maximum number of episodes to return.",
    )


class GetMemoryEpisodeRequest(BaseModel):
    episode_id: str = Field(..., description="Episode id returned by search or list tools.")


class ApprovalModel(BaseModel):
    decision: ApprovalDecision = Field(
        ...,
        description="Human approval state. Use only after explicit user approval.",
    )
    approved_by: str = Field(
        "user",
        description="Actor approving persistence. Defaults to user.",
    )
    note: Optional[str] = Field(
        None,
        description="Optional short note capturing user edits or caveats.",
    )


class EpisodeProposalModel(BaseModel):
    device_target: str = Field(..., description="Canonical target device or scope label.")
    operation_executed: str = Field(..., description="Operation that produced this lesson.")
    result: OperationResult
    root_cause: str = Field(..., description="Short technical reason for the observed outcome.")
    proposed_rule: str = Field(..., description="Exact rule to remember for future operations.")
    confidence: float = Field(..., ge=0.0, le=1.0)
    scope: Optional[ScopeType] = Field(
        None,
        description="Optional explicit scope. If omitted, the backend derives one conservatively.",
    )
    supersedes_episode_id: Optional[str] = Field(
        None,
        description="Optional prior episode to invalidate.",
    )
    evidence: Optional[str] = Field(
        None,
        description="Short validated evidence string. Do not send raw outputs.",
    )
    intent_class: Optional[str] = None
    phase: Optional[str] = None


class SaveEpisodeContextModel(BaseModel):
    device_names: List[str] = Field(
        ...,
        description="Canonical Nornir device_name values that were part of the operation.",
    )
    source_tool: Optional[str] = Field(
        None,
        description="Top-level tool used for the operation, for example configure_fabric_bulk.",
    )
    operation_type: Optional[str] = Field(
        None,
        description="Specific operation type if different from source_tool.",
    )
    intent_class: Optional[str] = None
    phase: Optional[str] = None
    platform: Optional[str] = None
    platforms: Optional[List[str]] = None
    fabric_role: Optional[str] = None
    fabric_roles: Optional[List[str]] = None
    validated_by: Optional[List[str]] = Field(
        None,
        description="Compact validators that support the root cause.",
    )
    evidence: Optional[str] = Field(
        None,
        description="Compact evidence summary. Do not include raw CLI outputs.",
    )
    tags: Optional[List[str]] = Field(
        None,
        description="Optional low-cardinality tags for later filtering.",
    )


class SaveEpisodeRequest(BaseModel):
    approval: ApprovalModel
    episode: EpisodeProposalModel
    context: SaveEpisodeContextModel

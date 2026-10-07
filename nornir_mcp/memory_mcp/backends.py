from __future__ import annotations

import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional
from uuid import uuid4

from inventory import InventoryResolver
from models import (
    GetMemoryEpisodeRequest,
    ListMemoryEpisodesRequest,
    SaveEpisodeRequest,
    ScopeType,
    SearchDeviceQuirksRequest,
)


SCOPE_PRIORITY = {
    "device": 400,
    "role_platform": 300,
    "platform": 200,
    "global": 100,
}
EPISODE_SCHEMA_VERSION = 1


class FileMemoryBackend:
    """Small persistent backend for operational episodes.

    This backend is intentionally simple and replaceable. The MCP tool contract
    should remain stable if a future Graphiti adapter replaces this class.
    """

    def __init__(self, store_path: Path, inventory: InventoryResolver):
        self.store_path = store_path
        self.inventory = inventory
        self._lock = Lock()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def search_device_quirks(self, request: SearchDeviceQuirksRequest) -> Dict[str, Any]:
        if not request.device_names:
            return {
                "success": False,
                "error_type": "ValidationError",
                "result": "device_names must contain at least one canonical Nornir device_name.",
            }

        devices = self.inventory.load_devices()
        target_platforms = sorted(set(request.platforms or self.inventory.platforms_for(request.device_names)))
        target_roles = sorted(set(request.fabric_roles or self.inventory.roles_for(request.device_names)))
        target_query = self._compact_text(
            " ".join(
                value
                for value in [request.query, request.operation_type, request.intent_class, request.phase]
                if value
            )
        )
        query_terms = self._tokenize(target_query)

        matches = []
        for episode in self._load_store().get("episodes", []):
            if episode.get("invalidated_at"):
                continue
            if not self._matches_requested_context(episode, request):
                continue

            scope = episode.get("scope", "global")
            if not self._is_applicable(
                episode=episode,
                scope=scope,
                device_names=request.device_names,
                platforms=target_platforms,
                roles=target_roles,
            ):
                continue

            score = SCOPE_PRIORITY.get(scope, 0)
            matched_fields = self._scope_matched_fields(
                episode=episode,
                scope=scope,
                device_names=request.device_names,
                platforms=target_platforms,
                roles=target_roles,
            )
            if request.phase and episode.get("phase") == request.phase:
                score += 40
                matched_fields.append("phase")
            if request.intent_class and episode.get("intent_class") == request.intent_class:
                score += 35
                matched_fields.append("intent_class")
            if request.operation_type and episode.get("operation_type") == request.operation_type:
                score += 25
                matched_fields.append("operation_type")
            text_score, text_matched_fields = self._text_match_score(query_terms, episode)
            score += text_score
            matched_fields.extend(text_matched_fields)
            matched_fields = self._dedupe_preserve_order(matched_fields)
            lesson_reason = episode.get("evidence") or episode.get("root_cause")

            matches.append(
                {
                    "score": score,
                    "scope": scope,
                    "device_name": episode.get("device_name"),
                    "rule": episode.get("proposed_rule"),
                    "matched_fields": matched_fields,
                    "reason": self._build_match_reason(episode, matched_fields, lesson_reason),
                    "lesson_reason": lesson_reason,
                    "confidence": episode.get("confidence"),
                    "valid_from": episode.get("created_at"),
                    "source_episode_id": episode.get("episode_id"),
                }
            )

        matches.sort(key=lambda item: (-item["score"], item["valid_from"] or ""))
        limited = [
            {
                "scope": item.get("scope"),
                "device_name": item.get("device_name"),
                "rule": item.get("rule"),
                "confidence": item.get("confidence"),
                "source_episode_id": item.get("source_episode_id"),
            }
            for item in matches[: request.limit]
        ]
        unknown_devices = [name for name in request.device_names if name not in devices]
        response = {
            "success": True,
            "matches": limited,
            "summary": f"{len(limited)} relevant quirk(s) found for this operation." if limited else "No relevant quirks found.",
        }
        if unknown_devices:
            response["unknown_devices"] = unknown_devices
        return response

    def list_memory_episodes(self, request: ListMemoryEpisodesRequest) -> Dict[str, Any]:
        requested_devices = set(request.device_names or [])
        requested_tags = set(request.tags or [])
        episodes = []

        for episode in self._load_store().get("episodes", []):
            if episode.get("invalidated_at") and not request.include_invalidated:
                continue
            if request.device_name and episode.get("device_name") != request.device_name:
                continue
            if requested_devices:
                episode_devices = set(episode.get("device_names") or [])
                if episode.get("device_name") not in requested_devices and not (episode_devices & requested_devices):
                    continue
            if request.scope and episode.get("scope") != request.scope:
                continue
            if request.platform and episode.get("platform") != request.platform:
                continue
            if request.fabric_role and episode.get("fabric_role") != request.fabric_role:
                continue
            if request.operation_type and episode.get("operation_type") != request.operation_type:
                continue
            if request.intent_class and episode.get("intent_class") != request.intent_class:
                continue
            if request.phase and episode.get("phase") != request.phase:
                continue
            if requested_tags and not requested_tags.issubset(set(episode.get("tags") or [])):
                continue
            episodes.append(self._public_episode_summary(episode))

        episodes.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        limited = episodes[: request.limit]
        return {
            "success": True,
            "episodes": limited,
            "count": len(limited),
            "summary": f"{len(limited)} episode(s) returned.",
        }

    def get_memory_episode(self, request: GetMemoryEpisodeRequest) -> Dict[str, Any]:
        for episode in self._load_store().get("episodes", []):
            if episode.get("episode_id") == request.episode_id:
                return {
                    "success": True,
                    "episode": self._public_episode_detail(episode),
                }
        return {
            "success": False,
            "error_type": "NotFound",
            "result": f"Episode {request.episode_id} was not found.",
        }

    def save_episode(self, request: SaveEpisodeRequest) -> Dict[str, Any]:
        if not request.context.device_names:
            return {
                "success": False,
                "error_type": "ValidationError",
                "result": "context.device_names must contain at least one canonical Nornir device_name.",
            }
        if self._contains_raw_config_like_text(request):
            return {
                "success": False,
                "error_type": "ValidationError",
                "result": "Episode text looks like raw configuration or long command output. Store only a compact lesson.",
            }

        now = self._utc_now()
        episode_id = f"ep_{uuid4().hex[:12]}"
        devices = self.inventory.load_devices()
        target_device = request.episode.device_target
        target_record = devices.get(target_device) or {}

        resolved_platforms = sorted(set(request.context.platforms or []))
        if request.context.platform and request.context.platform not in resolved_platforms:
            resolved_platforms.append(request.context.platform)
        if not resolved_platforms:
            resolved_platforms = self.inventory.platforms_for(request.context.device_names)

        resolved_roles = sorted(set(request.context.fabric_roles or []))
        if request.context.fabric_role and request.context.fabric_role not in resolved_roles:
            resolved_roles.append(request.context.fabric_role)
        if not resolved_roles:
            resolved_roles = self.inventory.roles_for(request.context.device_names)

        scope: ScopeType = request.episode.scope or self._derive_scope(
            device_target=target_device,
            target_record=target_record,
            platforms=resolved_platforms,
            roles=resolved_roles,
            device_names=request.context.device_names,
        )

        record = {
            "episode_id": episode_id,
            "schema_version": EPISODE_SCHEMA_VERSION,
            "created_at": now,
            "updated_at": now,
            "valid_from": now,
            "approved_at": now,
            "invalidated_at": None,
            "superseded_by": None,
            "scope": scope,
            "device_name": target_device,
            "device_names": request.context.device_names,
            "platform": target_record.get("platform") or self._first_or_none(resolved_platforms),
            "fabric_role": target_record.get("fabric_role") or self._first_or_none(resolved_roles),
            "groups": target_record.get("groups") or [],
            "operation_executed": self._compact_text(request.episode.operation_executed),
            "operation_type": self._compact_text(request.context.operation_type or request.context.source_tool),
            "intent_class": self._compact_text(request.episode.intent_class or request.context.intent_class),
            "phase": self._compact_text(request.episode.phase or request.context.phase),
            "result": request.episode.result,
            "root_cause": self._sanitize_free_text(request.episode.root_cause, 260),
            "proposed_rule": self._sanitize_free_text(request.episode.proposed_rule, 260),
            "confidence": request.episode.confidence,
            "evidence": self._sanitize_free_text(
                request.episode.evidence or request.context.evidence or self._build_evidence(request),
                240,
            ),
            "validated_by": request.context.validated_by or [],
            "source_tool": self._compact_text(request.context.source_tool),
            "tags": request.context.tags or [],
            "approval": {
                "decision": request.approval.decision,
                "approved_by": self._compact_text(request.approval.approved_by),
                "note": self._sanitize_free_text(request.approval.note, 160) if request.approval.note else None,
            },
            "supersedes_episode_id": request.episode.supersedes_episode_id,
        }
        record["search_text"] = self._build_search_text(record)
        record["content_hash"] = self._content_hash(record)

        with self._lock:
            store = self._load_store()
            duplicate = self._find_active_duplicate(store["episodes"], record["content_hash"])
            if duplicate:
                return {
                    "success": True,
                    "duplicate": True,
                    "episode_id": duplicate.get("episode_id"),
                    "stored_scope": duplicate.get("scope"),
                    "message": "Duplicate active episode already exists; no new episode was saved.",
                }
            superseded = self._mark_superseded(
                episodes=store["episodes"],
                supersedes_episode_id=request.episode.supersedes_episode_id,
                replacement_id=episode_id,
                timestamp=now,
            )
            store["episodes"].append(record)
            self._write_store(store)

        return {
            "success": True,
            "episode_id": episode_id,
            "stored_scope": scope,
            "superseded_episode_id": superseded,
            "message": "Episode saved successfully.",
        }

    def _find_active_duplicate(self, episodes: List[dict], content_hash: str) -> Optional[dict]:
        for episode in episodes:
            if episode.get("content_hash") == content_hash and not episode.get("invalidated_at"):
                return episode
        return None

    def _derive_scope(
        self,
        device_target: str,
        target_record: dict,
        platforms: List[str],
        roles: List[str],
        device_names: List[str],
    ) -> ScopeType:
        if device_target and device_target in device_names:
            return "device"
        if target_record.get("platform") and target_record.get("fabric_role"):
            return "role_platform"
        if platforms and roles:
            return "role_platform"
        if platforms:
            return "platform"
        return "global"

    def _mark_superseded(
        self,
        episodes: List[dict],
        supersedes_episode_id: Optional[str],
        replacement_id: str,
        timestamp: str,
    ) -> Optional[str]:
        if not supersedes_episode_id:
            return None
        for episode in episodes:
            if episode.get("episode_id") == supersedes_episode_id:
                episode["invalidated_at"] = timestamp
                episode["updated_at"] = timestamp
                episode["superseded_by"] = replacement_id
                return supersedes_episode_id
        return None

    def _is_applicable(
        self,
        episode: dict,
        scope: str,
        device_names: List[str],
        platforms: List[str],
        roles: List[str],
    ) -> bool:
        if scope == "device":
            return episode.get("device_name") in device_names
        if scope == "role_platform":
            return bool(
                episode.get("platform")
                and episode.get("fabric_role")
                and episode.get("platform") in platforms
                and episode.get("fabric_role") in roles
            )
        if scope == "platform":
            return bool(episode.get("platform") and episode.get("platform") in platforms)
        return True

    def _scope_matched_fields(
        self,
        episode: dict,
        scope: str,
        device_names: List[str],
        platforms: List[str],
        roles: List[str],
    ) -> List[str]:
        if scope == "device" and episode.get("device_name") in device_names:
            matched = ["scope:device", "device_name"]
            if episode.get("platform") in platforms:
                matched.append("platform")
            if episode.get("fabric_role") in roles:
                matched.append("fabric_role")
            return matched
        if scope == "role_platform":
            matched = ["scope:role_platform"]
            if episode.get("platform") in platforms:
                matched.append("platform")
            if episode.get("fabric_role") in roles:
                matched.append("fabric_role")
            return matched
        if scope == "platform" and episode.get("platform") in platforms:
            return ["scope:platform", "platform"]
        if scope == "global":
            return ["scope:global"]
        return [f"scope:{scope}"]

    def _matches_requested_context(self, episode: dict, request: SearchDeviceQuirksRequest) -> bool:
        # Intent and phase define applicability. The concrete operation/tool is
        # only a ranking signal because the same lesson may be reused through a
        # different execution path (for example, device-bulk vs fabric-bulk).
        for field_name in ("intent_class", "phase"):
            requested = getattr(request, field_name, None)
            stored = episode.get(field_name)
            if requested and stored and stored != requested:
                return False
        return True

    def _text_match_score(self, query_terms: set[str], episode: dict) -> tuple[int, List[str]]:
        if not query_terms:
            return 0, []
        score = 0
        matched_fields = []
        for field_name in ["search_text", "proposed_rule", "root_cause"]:
            field_score = self._text_overlap_score(query_terms, self._tokenize(episode.get(field_name, "")))
            score += field_score
            if field_score:
                matched_fields.append(f"query_terms:{field_name}")
        if matched_fields:
            matched_fields.insert(0, "query_terms")
        return score, matched_fields

    def _build_match_reason(self, episode: dict, matched_fields: List[str], lesson_reason: Optional[str]) -> str:
        parts = []
        scope = episode.get("scope", "global")
        if f"scope:{scope}" in matched_fields:
            if scope == "role_platform":
                parts.append(f"scope=role_platform({episode.get('platform')}/{episode.get('fabric_role')})")
            elif scope == "platform":
                parts.append(f"scope=platform({episode.get('platform')})")
            elif scope == "device":
                parts.append(f"scope=device({episode.get('device_name')})")
            else:
                parts.append(f"scope={scope}")
        for field_name in ["phase", "intent_class", "operation_type", "platform", "fabric_role", "device_name"]:
            if field_name in matched_fields and episode.get(field_name):
                parts.append(f"{field_name}={episode.get(field_name)}")
        if "query_terms" in matched_fields:
            parts.append("query_terms matched stored lesson text")

        reason = "Matched " + ", ".join(parts) + "." if parts else "Matched applicable stored lesson."
        if lesson_reason:
            reason = f"{reason} Lesson: {lesson_reason}"
        return self._sanitize_free_text(reason, 360) or reason

    def _dedupe_preserve_order(self, values: List[str]) -> List[str]:
        seen = set()
        deduped = []
        for value in values:
            if value not in seen:
                seen.add(value)
                deduped.append(value)
        return deduped

    def _build_evidence(self, request: SaveEpisodeRequest) -> str:
        validators = ", ".join(request.context.validated_by or [])
        pieces = [
            f"Result={request.episode.result}",
            f"Tool={request.context.source_tool or request.context.operation_type}",
            f"Validators={validators}" if validators else "",
        ]
        return self._compact_text("; ".join(piece for piece in pieces if piece)) or ""

    def _build_search_text(self, record: dict) -> str:
        fields = [
            record.get("device_name"),
            record.get("platform"),
            record.get("fabric_role"),
            record.get("operation_executed"),
            record.get("operation_type"),
            record.get("intent_class"),
            record.get("phase"),
            record.get("root_cause"),
            record.get("proposed_rule"),
            record.get("evidence"),
            " ".join(record.get("validated_by") or []),
            " ".join(record.get("tags") or []),
        ]
        return self._compact_text(" ".join(str(field) for field in fields if field)) or ""

    def _public_episode_summary(self, episode: dict) -> Dict[str, Any]:
        return {
            "episode_id": episode.get("episode_id"),
            "created_at": episode.get("created_at"),
            "updated_at": episode.get("updated_at"),
            "invalidated_at": episode.get("invalidated_at"),
            "superseded_by": episode.get("superseded_by"),
            "scope": episode.get("scope"),
            "device_name": episode.get("device_name"),
            "platform": episode.get("platform"),
            "fabric_role": episode.get("fabric_role"),
            "operation_type": episode.get("operation_type"),
            "intent_class": episode.get("intent_class"),
            "phase": episode.get("phase"),
            "rule": episode.get("proposed_rule"),
            "confidence": episode.get("confidence"),
            "tags": episode.get("tags") or [],
        }

    def _public_episode_detail(self, episode: dict) -> Dict[str, Any]:
        detail = self._public_episode_summary(episode)
        detail.update(
            {
                "schema_version": episode.get("schema_version"),
                "device_names": episode.get("device_names") or [],
                "operation_executed": episode.get("operation_executed"),
                "result": episode.get("result"),
                "root_cause": episode.get("root_cause"),
                "evidence": episode.get("evidence"),
                "validated_by": episode.get("validated_by") or [],
                "source_tool": episode.get("source_tool"),
                "approval": episode.get("approval") or {},
                "supersedes_episode_id": episode.get("supersedes_episode_id"),
            }
        )
        return detail

    def _content_hash(self, record: dict) -> str:
        stable_payload = {
            "device_name": record.get("device_name"),
            "scope": record.get("scope"),
            "operation_executed": record.get("operation_executed"),
            "root_cause": record.get("root_cause"),
            "proposed_rule": record.get("proposed_rule"),
        }
        raw = json.dumps(stable_payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _sanitize_free_text(self, value: Optional[str], max_len: int) -> Optional[str]:
        value = self._redact_secrets(value)
        value = self._compact_text(value)
        return value[:max_len] if value else value

    def _compact_text(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        compacted = re.sub(r"\s+", " ", str(value)).strip()
        return compacted or None

    def _redact_secrets(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        redacted = str(value)
        patterns = [
            (r"(?i)\bpassword\s+(\S+)", "password <redacted>"),
            (r"(?i)\bpassword\b\s*[:=]\s*\S+", "password=<redacted>"),
            (r"(?i)\bsecret\s+(\S+)", "secret <redacted>"),
            (r"(?i)\bsecret\b\s*[:=]\s*\S+", "secret=<redacted>"),
            (r"(?i)\bapi[_-]?key\b\s*[:=]\s*\S+", "api_key=<redacted>"),
            (r"(?i)\btoken\b\s*[:=]\s*\S+", "token=<redacted>"),
            (r"(?i)\bbearer\s+[a-z0-9._~+/=-]+", "Bearer <redacted>"),
            (r"(?i)\bsnmp-server\s+community\s+\S+", "snmp-server community <redacted>"),
            (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "<redacted private key>"),
        ]
        for pattern, replacement in patterns:
            redacted = re.sub(pattern, replacement, redacted, flags=re.DOTALL)
        return redacted

    def _contains_raw_config_like_text(self, request: SaveEpisodeRequest) -> bool:
        values = [
            request.episode.root_cause,
            request.episode.proposed_rule,
            request.episode.evidence,
            request.context.evidence,
        ]
        text = "\n".join(value for value in values if value)
        if len(text) > 2500:
            return True
        config_markers = [
            r"(?im)^\s*interface\s+\S+",
            r"(?im)^\s*router\s+(bgp|ospf)\b",
            r"(?im)^\s*vlan\s+\d+",
            r"(?im)^\s*ip\s+route\s+",
            r"(?im)^\s*line\s+vty\b",
        ]
        marker_count = sum(1 for pattern in config_markers if re.search(pattern, text))
        return marker_count >= 3

    def _tokenize(self, value: Optional[str]) -> set[str]:
        if not value:
            return set()
        return {
            token
            for token in re.findall(r"[a-zA-Z0-9_.-]+", value.lower())
            if len(token) > 2
        }

    def _text_overlap_score(self, left: set[str], right: set[str]) -> int:
        if not left or not right:
            return 0
        return min(30, len(left & right) * 6)

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def _first_or_none(self, values: List[str]) -> Optional[str]:
        return values[0] if values else None

    def _load_store(self) -> dict:
        if not self.store_path.exists():
            return {"version": 1, "episodes": []}
        try:
            with self.store_path.open("r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if not isinstance(loaded, dict):
                return {"version": 1, "episodes": []}
            loaded.setdefault("version", 1)
            loaded.setdefault("episodes", [])
            return loaded
        except Exception:
            return {"version": 1, "episodes": []}

    def _write_store(self, payload: dict) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=self.store_path.parent,
            encoding="utf-8",
        ) as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=True)
            temp_path = Path(fh.name)
        temp_path.replace(self.store_path)

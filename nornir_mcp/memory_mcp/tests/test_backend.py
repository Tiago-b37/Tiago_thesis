from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backends import FileMemoryBackend
from models import (
    ApprovalModel,
    EpisodeProposalModel,
    GetMemoryEpisodeRequest,
    ListMemoryEpisodesRequest,
    SaveEpisodeContextModel,
    SaveEpisodeRequest,
    SearchDeviceQuirksRequest,
)


class FakeInventory:
    devices = {
        "leaf1-dc2": {
            "device_name": "leaf1-dc2",
            "platform": "eos",
            "fabric_role": "leaf",
            "groups": ["leafs"],
        },
        "leaf2-dc2": {
            "device_name": "leaf2-dc2",
            "platform": "eos",
            "fabric_role": "leaf",
            "groups": ["leafs"],
        },
        "spine1-dc2": {
            "device_name": "spine1-dc2",
            "platform": "eos",
            "fabric_role": "spine",
            "groups": ["spines"],
        },
    }

    def load_devices(self):
        return self.devices

    def platforms_for(self, device_names):
        return sorted(
            {
                self.devices[name]["platform"]
                for name in device_names
                if name in self.devices and self.devices[name].get("platform")
            }
        )

    def roles_for(self, device_names):
        return sorted(
            {
                self.devices[name]["fabric_role"]
                for name in device_names
                if name in self.devices and self.devices[name].get("fabric_role")
            }
        )


def build_backend(tmp_path):
    return FileMemoryBackend(store_path=tmp_path / "episodes.json", inventory=FakeInventory())


def build_save_request(
    *,
    rule="For EOS leaf dataplane, include flood_vteps for every other participating leaf VTEP.",
    root_cause="Head-end replication needs explicit remote VTEPs.",
    evidence="check_dataplane_summary confirmed VNI 10010 up.",
    device_target="leaf1-dc2",
    supersedes_episode_id=None,
    operation_type="configure_fabric_bulk",
    intent_class="zero_to_hero_fabric",
    phase="dataplane",
    tags=None,
):
    return SaveEpisodeRequest(
        approval=ApprovalModel(decision="approved", approved_by="user"),
        episode=EpisodeProposalModel(
            device_target=device_target,
            operation_executed="configure_fabric_bulk",
            result="success",
            root_cause=root_cause,
            proposed_rule=rule,
            confidence=0.9,
            supersedes_episode_id=supersedes_episode_id,
            evidence=evidence,
            intent_class=intent_class,
            phase=phase,
        ),
        context=SaveEpisodeContextModel(
            device_names=["leaf1-dc2", "leaf2-dc2"],
            source_tool="configure_fabric_bulk",
            operation_type=operation_type,
            intent_class=intent_class,
            phase=phase,
            validated_by=["check_dataplane_summary"],
            tags=tags or ["vxlan", "her"],
        ),
    )


def test_search_empty_store_returns_no_matches(tmp_path):
    backend = build_backend(tmp_path)

    result = backend.search_device_quirks(
        SearchDeviceQuirksRequest(
            device_names=["leaf1-dc2"],
            operation_type="configure_fabric_bulk",
            intent_class="zero_to_hero_fabric",
            phase="dataplane",
        )
    )

    assert result["success"] is True
    assert result["matches"] == []
    assert "normalized_context" not in result


def test_save_and_search_episode(tmp_path):
    backend = build_backend(tmp_path)

    saved = backend.save_episode(build_save_request())
    result = backend.search_device_quirks(
        SearchDeviceQuirksRequest(
            device_names=["leaf1-dc2", "leaf2-dc2"],
            operation_type="configure_fabric_bulk",
            intent_class="zero_to_hero_fabric",
            phase="dataplane",
            query="vxlan head-end replication flood vteps",
        )
    )

    assert saved["success"] is True
    assert saved.get("duplicate") is not True
    assert result["success"] is True
    assert result["matches"]
    assert result["matches"][0]["source_episode_id"] == saved["episode_id"]
    assert "flood_vteps" in result["matches"][0]["rule"]
    assert result["matches"][0]["scope"]
    assert result["matches"][0]["confidence"] == 0.9
    assert "matched_fields" not in result["matches"][0]
    assert "reason" not in result["matches"][0]
    assert "lesson_reason" not in result["matches"][0]


def test_search_allows_operation_type_mismatch_when_context_matches(tmp_path):
    backend = build_backend(tmp_path)
    saved = backend.save_episode(
        build_save_request(
            operation_type="configure_device_bulk",
            intent_class="day_n_change",
            phase="underlay",
            rule="Verify the peer AS when an underlay BGP session remains Active.",
            root_cause="The configured remote AS did not match the peer local AS.",
            tags=["bgp", "underlay", "asn-mismatch"],
        )
    )

    result = backend.search_device_quirks(
        SearchDeviceQuirksRequest(
            device_names=["leaf1-dc2"],
            operation_type="configure_fabric_bulk",
            intent_class="day_n_change",
            phase="underlay",
            query="BGP Active remote AS mismatch",
        )
    )

    assert result["success"] is True
    assert [item["source_episode_id"] for item in result["matches"]] == [saved["episode_id"]]


def test_search_ranks_exact_operation_type_above_compatible_mismatch(tmp_path):
    backend = build_backend(tmp_path)
    compatible = backend.save_episode(
        build_save_request(
            operation_type="configure_device_bulk",
            intent_class="day_n_change",
            phase="underlay",
            rule="Compatible lesson for a BGP peer-AS mismatch.",
            root_cause="A device-level operation found the incorrect peer AS.",
            tags=["bgp", "underlay"],
        )
    )
    exact = backend.save_episode(
        build_save_request(
            operation_type="configure_fabric_bulk",
            intent_class="day_n_change",
            phase="underlay",
            rule="Exact-operation lesson for a BGP peer-AS mismatch.",
            root_cause="A fabric-level operation found the incorrect peer AS.",
            tags=["bgp", "underlay"],
        )
    )

    result = backend.search_device_quirks(
        SearchDeviceQuirksRequest(
            device_names=["leaf1-dc2"],
            operation_type="configure_fabric_bulk",
            intent_class="day_n_change",
            phase="underlay",
            query="BGP peer AS mismatch",
        )
    )

    ids = [item["source_episode_id"] for item in result["matches"]]
    assert ids[0] == exact["episode_id"]
    assert compatible["episode_id"] in ids


def test_search_skips_explicit_context_mismatches(tmp_path):
    backend = build_backend(tmp_path)
    backend.save_episode(
        build_save_request(
            intent_class="day_n_change",
            phase="vlan_migration",
        )
    )

    result = backend.search_device_quirks(
        SearchDeviceQuirksRequest(
            device_names=["leaf1-dc2", "leaf2-dc2"],
            operation_type="configure_fabric_bulk",
            intent_class="zero_to_hero_fabric",
            phase="dataplane",
            query="vxlan head-end replication flood vteps",
        )
    )

    assert result["success"] is True
    assert result["matches"] == []


def test_duplicate_save_does_not_create_second_episode(tmp_path):
    backend = build_backend(tmp_path)

    first = backend.save_episode(build_save_request())
    duplicate = backend.save_episode(build_save_request())
    listed = backend.list_memory_episodes(ListMemoryEpisodesRequest())

    assert first["success"] is True
    assert duplicate["success"] is True
    assert duplicate["duplicate"] is True
    assert duplicate["episode_id"] == first["episode_id"]
    assert listed["count"] == 1


def test_superseded_episode_is_hidden_by_default(tmp_path):
    backend = build_backend(tmp_path)

    old = backend.save_episode(build_save_request(rule="Old dataplane rule."))
    new = backend.save_episode(
        build_save_request(
            rule="New dataplane rule.",
            root_cause="The old rule was too narrow.",
            supersedes_episode_id=old["episode_id"],
        )
    )

    active = backend.list_memory_episodes(ListMemoryEpisodesRequest())
    all_episodes = backend.list_memory_episodes(ListMemoryEpisodesRequest(include_invalidated=True))
    old_detail = backend.get_memory_episode(GetMemoryEpisodeRequest(episode_id=old["episode_id"]))

    assert new["superseded_episode_id"] == old["episode_id"]
    assert active["count"] == 1
    assert active["episodes"][0]["episode_id"] == new["episode_id"]
    assert all_episodes["count"] == 2
    assert old_detail["episode"]["invalidated_at"] is not None
    assert old_detail["episode"]["superseded_by"] == new["episode_id"]


def test_redacts_sensitive_values(tmp_path):
    backend = build_backend(tmp_path)

    saved = backend.save_episode(
        build_save_request(
            root_cause="Login failed because password admin123 was reused.",
            evidence="token=abc123 and snmp-server community public were present.",
        )
    )
    detail = backend.get_memory_episode(GetMemoryEpisodeRequest(episode_id=saved["episode_id"]))

    rendered = str(detail["episode"])
    assert "admin123" not in rendered
    assert "abc123" not in rendered
    assert "public" not in rendered
    assert "<redacted>" in rendered


def test_list_filters_by_tags_and_phase(tmp_path):
    backend = build_backend(tmp_path)
    backend.save_episode(build_save_request(tags=["vxlan", "her"]))
    backend.save_episode(
        build_save_request(
            rule="OSPF retries should wait exactly 10 seconds.",
            root_cause="OSPF needs convergence time.",
            evidence="check_ospf_summary converged on retry.",
            device_target="spine1-dc2",
            tags=["ospf"],
        )
    )

    result = backend.list_memory_episodes(
        ListMemoryEpisodesRequest(phase="dataplane", tags=["vxlan"])
    )

    assert result["count"] == 1
    assert result["episodes"][0]["tags"] == ["vxlan", "her"]


def test_rejects_raw_config_like_episode(tmp_path):
    backend = build_backend(tmp_path)

    result = backend.save_episode(
        build_save_request(
            evidence="""
            interface Ethernet1
              ip address 10.0.0.0/31
            router ospf 1
              network 10.0.0.0/31 area 0
            vlan 10
              name users
            """,
        )
    )

    assert result["success"] is False
    assert result["error_type"] == "ValidationError"

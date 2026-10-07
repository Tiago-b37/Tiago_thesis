from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - defensive fallback
    yaml = None


class InventoryResolver:
    """Read canonical device metadata from the existing Nornir inventory files."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path(__file__).resolve().parent.parent
        self.hosts_path = self.base_dir / "conf" / "hosts.yaml"
        self.groups_path = self.base_dir / "conf" / "groups.yaml"

    def _load_yaml(self, path: Path) -> dict:
        if yaml is None or not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
        except Exception:
            return {}

    def load_devices(self) -> Dict[str, dict]:
        hosts = self._load_yaml(self.hosts_path)
        groups = self._load_yaml(self.groups_path)
        devices: Dict[str, dict] = {}

        for device_name, attrs in (hosts.items() if isinstance(hosts, dict) else []):
            attrs = attrs or {}
            group_names = attrs.get("groups") or []
            if isinstance(group_names, str):
                group_names = [group_names]

            fabric_role = None
            for group_name in group_names:
                group_data = groups.get(group_name) or {}
                role_candidate = (group_data.get("data") or {}).get("fabric_role")
                if role_candidate:
                    fabric_role = role_candidate
                    break

            devices[device_name] = {
                "device_name": device_name,
                "platform": attrs.get("platform"),
                "fabric_role": fabric_role,
                "groups": group_names,
            }

        return devices

    def platforms_for(self, device_names: List[str]) -> List[str]:
        devices = self.load_devices()
        values = {
            devices[name]["platform"]
            for name in device_names
            if name in devices and devices[name].get("platform")
        }
        return sorted(values)

    def roles_for(self, device_names: List[str]) -> List[str]:
        devices = self.load_devices()
        values = {
            devices[name]["fabric_role"]
            for name in device_names
            if name in devices and devices[name].get("fabric_role")
        }
        return sorted(values)

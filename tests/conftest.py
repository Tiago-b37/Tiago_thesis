"""Test-only stubs for unit tests that do not use the live Nornir runtime."""

import sys
import types


fake_nornir_ops = types.ModuleType("nornir_ops")


class FakeNornirManager:
    """Minimal constructor used while importing pure server guard helpers."""

    pass


fake_nornir_ops.NornirManager = FakeNornirManager
sys.modules.setdefault("nornir_ops", fake_nornir_ops)

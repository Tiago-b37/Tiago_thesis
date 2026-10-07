"""Regression tests for Nornir failed-host state handling.

These tests use a small in-memory Nornir double and never contact devices.
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "nornir_mcp" / "nornir_ops.py"


def _load_nornir_ops():
    fake_nornir = types.ModuleType("nornir")
    fake_nornir.InitNornir = lambda **_: None

    fake_core = types.ModuleType("nornir.core")
    fake_core.Nornir = object

    fake_task = types.ModuleType("nornir.core.task")
    fake_task.Result = object
    fake_task.Task = object

    fake_napalm_tasks = types.ModuleType("nornir_napalm.plugins.tasks")
    fake_napalm_tasks.napalm_get = object()
    fake_napalm_tasks.napalm_ping = object()

    module_stubs = {
        "nornir": fake_nornir,
        "nornir.core": fake_core,
        "nornir.core.task": fake_task,
        "nornir_napalm": types.ModuleType("nornir_napalm"),
        "nornir_napalm.plugins": types.ModuleType("nornir_napalm.plugins"),
        "nornir_napalm.plugins.tasks": fake_napalm_tasks,
    }
    previous = {name: sys.modules.get(name) for name in module_stubs}
    sys.modules.update(module_stubs)
    try:
        spec = importlib.util.spec_from_file_location(
            "nornir_ops_state_under_test", MODULE_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, prior_module in previous.items():
            if prior_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior_module


nornir_ops = _load_nornir_ops()


class FakeResult:
    def __init__(self, result=None, failed=False, exception=None):
        self.result = result
        self.failed = failed
        self.exception = exception


class FakeMultiResult(list):
    @property
    def failed(self):
        return any(getattr(item, "failed", False) for item in self)


class FakeHost:
    def __init__(self, name):
        self.name = name


class FakeInventory:
    def __init__(self, names):
        self.hosts = {name: FakeHost(name) for name in names}


class FakeState:
    def __init__(self):
        self.failed_hosts = set()
        self.recovered = []

    def recover_host(self, device_name):
        self.failed_hosts.discard(device_name)
        self.recovered.append(device_name)


class FakeFilteredNornir:
    def __init__(self, parent, names):
        self.parent = parent
        self.inventory = FakeInventory(names)
        self.config = None

    def run(self, **_):
        for name in self.inventory.hosts:
            assert name not in self.parent.data.failed_hosts

        result = self.parent.outcomes.pop(0)
        for name, host_result in result.items():
            if getattr(host_result, "failed", False):
                self.parent.data.failed_hosts.add(name)
        return result


class FakeNornir:
    def __init__(self, names, outcomes):
        self.inventory = FakeInventory(names)
        self.data = FakeState()
        self.outcomes = list(outcomes)

    def filter(self, name=None, filter_func=None):
        if name is not None:
            names = [name] if name in self.inventory.hosts else []
        else:
            names = [
                host_name
                for host_name, host in self.inventory.hosts.items()
                if filter_func(host)
            ]
        return FakeFilteredNornir(self, names)


def make_manager(names, outcomes):
    manager = nornir_ops.NornirManager.__new__(nornir_ops.NornirManager)
    manager.nr = FakeNornir(names, outcomes)
    return manager


def test_failed_read_does_not_poison_the_next_explicit_read():
    failure = RuntimeError("detail getter failed")
    manager = make_manager(
        ["leaf1"],
        [
            {"leaf1": FakeMultiResult([FakeResult(failed=True, exception=failure)])},
            {"leaf1": FakeMultiResult([FakeResult(result={"peer": "Established"})])},
        ],
    )

    first = asyncio.run(
        manager._run_host_task("leaf1", object(), "failed detail getter")
    )
    assert first["success"] is False
    assert manager.nr.data.failed_hosts == {"leaf1"}

    second = asyncio.run(
        manager._run_host_task("leaf1", object(), "next explicit read")
    )
    assert second == {
        "host": "leaf1",
        "success": True,
        "result": {"peer": "Established"},
    }
    assert manager.nr.data.recovered == ["leaf1"]
    assert manager.nr.data.failed_hosts == set()


def test_empty_single_host_result_is_an_explicit_failure():
    manager = make_manager(["leaf1"], [{}])

    result = asyncio.run(manager._run_host_task("leaf1", object(), "empty read"))

    assert result["success"] is False
    assert result["error_type"] == "ResultMissingHost"


def test_multi_host_result_marks_each_missing_target():
    manager = make_manager(
        ["leaf1", "leaf2"],
        [{"leaf1": FakeMultiResult([FakeResult(result="ok")])}],
    )

    result = asyncio.run(
        manager._run_hosts_task(["leaf1", "leaf2"], object(), "partial read")
    )

    assert result["results"]["leaf1"] == {"success": True, "result": "ok"}
    assert result["results"]["leaf2"]["success"] is False
    assert result["results"]["leaf2"]["error_type"] == "ResultMissingHost"

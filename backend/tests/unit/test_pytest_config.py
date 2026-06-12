"""Phase 0 — pytest must be configured with pytest-asyncio in auto mode.

Expected to FAIL in red phase: `pyproject.toml` does not yet declare
`[tool.pytest.ini_options]` with `asyncio_mode = "auto"`.

Two layers of assertions:
    1. `backend/pyproject.toml` exists and configures pytest-asyncio auto mode.
    2. A trivial async function (NO explicit `@pytest.mark.asyncio`) is treated
       as a coroutine test under auto mode — proving the plugin actually
       picked up the config at runtime.

If `asyncio_mode` is unset or strict, the un-marked async function below is
collected as a regular (non-coroutine) test and pytest emits a runtime warning
"async def functions are not natively supported" → the assertion that the
coroutine actually executed fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_declares_asyncio_auto_mode() -> None:
    """`backend/pyproject.toml` must set pytest-asyncio mode to auto."""
    import tomllib  # noqa: PLC0415 — std lib, py3.11+

    pyproject = BACKEND_ROOT / "pyproject.toml"
    assert pyproject.exists(), (
        f"pyproject.toml not found at {pyproject} — implementer must create it"
    )

    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    pytest_cfg = (
        data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    )
    assert pytest_cfg.get("asyncio_mode") == "auto", (
        "pytest-asyncio must be configured with asyncio_mode = 'auto' "
        "in [tool.pytest.ini_options]; "
        f"current value: {pytest_cfg.get('asyncio_mode')!r}"
    )


# Sentinel module-level flag so we can assert the coroutine actually ran.
_COROUTINE_RAN: dict[str, bool] = {"flag": False}


async def test_unmarked_async_function_runs_under_auto_mode() -> None:
    """No `@pytest.mark.asyncio`: only auto-mode pytest-asyncio runs it as coroutine.

    If auto mode is off → pytest collects this as a regular sync test, never
    awaits the coroutine, the flag stays False, and the post-check fails.
    """
    import asyncio  # noqa: PLC0415

    await asyncio.sleep(0)
    _COROUTINE_RAN["flag"] = True
    assert _COROUTINE_RAN["flag"], "coroutine body must have executed"


def test_conftest_exposes_required_fixtures() -> None:
    """Edge: conftest must expose the canonical fixtures the spec mandates.

    The implementer needs `app_client`, `db_engine`, `db_session`, `env_vars`,
    `pg_container` available via conftest. We assert by attempting to import
    the conftest module and inspecting fixture names registered on it.
    """
    import importlib  # noqa: PLC0415
    import inspect  # noqa: PLC0415

    conftest_mod = importlib.import_module("tests.conftest")

    required_fixtures = {
        "env_vars",
        "pg_container",
        "sync_db_url",
        "async_db_url",
        "db_engine",
        "db_session",
        "app_client",
    }
    declared = {
        name
        for name, obj in inspect.getmembers(conftest_mod)
        if callable(obj) and hasattr(obj, "_pytestfixturefunction")
    }
    missing = required_fixtures - declared
    assert not missing, (
        f"conftest is missing required fixtures: {sorted(missing)}; "
        f"declared: {sorted(declared)}"
    )

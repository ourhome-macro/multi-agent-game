from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["AGENT_RUNTIME"] = "memory"


def _patch_pytest_tmpdir_acl_for_windows() -> None:
    """Keep pytest temp dirs readable under the Windows Codex sandbox token."""
    if os.name != "nt" or sys.version_info < (3, 12):
        return

    import _pytest.pathlib as pytest_pathlib
    import _pytest.tmpdir as pytest_tmpdir

    project_root = Path(__file__).resolve().parents[1]
    pytest_root = project_root / "pytest_tmp_root"
    os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(pytest_root))
    pytest_root.mkdir(mode=0o777, exist_ok=True)

    def getbasetemp(self: pytest_tmpdir.TempPathFactory) -> Path:
        if self._basetemp is not None:
            return self._basetemp

        if self._given_basetemp is not None:
            basetemp = self._given_basetemp
            if basetemp.exists():
                pytest_tmpdir.rm_rf(basetemp)
            basetemp.mkdir(mode=0o777)
            basetemp = basetemp.resolve()
        else:
            temproot = Path(
                os.environ.get("PYTEST_DEBUG_TEMPROOT") or tempfile.gettempdir()
            ).resolve()
            user = pytest_tmpdir.get_user() or "unknown"
            rootdir = temproot.joinpath(f"pytest-of-{user}")
            try:
                rootdir.mkdir(mode=0o777, exist_ok=True)
            except OSError:
                rootdir = temproot.joinpath("pytest-of-unknown")
                rootdir.mkdir(mode=0o777, exist_ok=True)

            keep = self._retention_count
            if self._retention_policy == "none":
                keep = 0
            basetemp = pytest_pathlib.make_numbered_dir_with_cleanup(
                prefix="pytest-",
                root=rootdir,
                keep=keep,
                lock_timeout=pytest_pathlib.LOCK_TIMEOUT,
                mode=0o777,
            )

        self._basetemp = basetemp
        self._trace("new basetemp", basetemp)
        return basetemp

    def mktemp(
        self: pytest_tmpdir.TempPathFactory, basename: str, numbered: bool = True
    ) -> Path:
        basename = self._ensure_relative_to_basetemp(basename)
        if not numbered:
            path = self.getbasetemp().joinpath(basename)
            path.mkdir(mode=0o777)
        else:
            path = pytest_pathlib.make_numbered_dir(
                root=self.getbasetemp(),
                prefix=basename,
                mode=0o777,
            )
            self._trace("mktemp", path)
        return path

    pytest_tmpdir.TempPathFactory.getbasetemp = getbasetemp
    pytest_tmpdir.TempPathFactory.mktemp = mktemp


_patch_pytest_tmpdir_acl_for_windows()

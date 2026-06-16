# Pytest Windows Temp ACL

## Problem

On Windows with Python 3.12 and pytest 9, pytest creates `tmp_path` roots with
`mode=0o700`. Under the Codex sandbox token this can produce directories whose
ACL contains only `SYSTEM`, `Administrators`, and `OWNER RIGHTS`.

The current process can have the `Administrators` group marked deny-only, so
pytest may create `basetemp` and then fail to list or clean it:

```text
PermissionError: [WinError 5] Access is denied: ...\basetemp
```

This is not solved by a virtual environment. A venv isolates packages; it does
not change how Python 3.12 maps `mkdir(mode=0o700)` to Windows ACLs.

## Current Fix

`tests/conftest.py` applies a Windows + Python 3.12-only pytest tempdir patch:

- default pytest temp root is `pytest_tmp_root/` under the repo;
- the root is covered by `.gitignore` via `pytest_tmp*/`;
- pytest temp directories are created with inherited ACL behavior instead of
  private `0o700` ACLs;
- production runtime code is not affected.

Run tests with:

```powershell
py -3.12 -m pytest -p no:cacheprovider -q tests --tb=short
```

Do not run the test suite as Administrator just to bypass this. That hides the
same ACL problem and makes local CI behavior harder to reproduce.

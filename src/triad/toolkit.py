"""Built-in tools. Each returns plain JSON-serialisable data.

Tools that report a check return {"status", "detail", "metrics"} so the Tracker
can turn them into a `Check` without knowing which stack produced them.

Process execution is limited to a short allowlist and never uses a shell.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from triad.config import Config
from triad.tools import ToolRegistry

_ALLOWED = {"git", "npm", "ruff", "pytest"}
_PYTHON = re.compile(r"python[\d.]*")
_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".next", ".triad", ".pytest_cache", ".ruff_cache", ".mypy_cache",
}  # fmt: skip
_LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock"}
_SOURCE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte",
    ".css", ".scss", ".html", ".sql", ".go", ".rs",
}  # fmt: skip
_MARKERS = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")

Result = dict[str, Any]


def build_registry(config: Config) -> ToolRegistry:
    root = config.workdir
    registry = ToolRegistry()

    # ---- helpers -------------------------------------------------------------------------

    def run(argv: list[str], timeout: int = 120) -> Result:
        exe = Path(argv[0]).stem.lower()
        if exe not in _ALLOWED and not _PYTHON.fullmatch(exe):
            raise PermissionError(f"executable not allowed: {argv[0]}")
        env = {**os.environ, "CI": "1", "NO_COLOR": "1"}
        try:
            proc = subprocess.run(
                argv, cwd=root, capture_output=True, text=True, timeout=timeout, env=env
            )
        except FileNotFoundError:
            return {"code": 127, "stdout": "", "stderr": f"{exe}: command not found"}
        except subprocess.TimeoutExpired:
            return {"code": 124, "stdout": "", "stderr": f"{exe}: timed out after {timeout}s"}
        return {"code": proc.returncode, "stdout": proc.stdout or "", "stderr": proc.stderr or ""}

    def tail(result: Result, lines: int = 12) -> str:
        text = (result["stdout"] + result["stderr"]).strip().splitlines()
        return "\n".join(text[-lines:])

    def files() -> Iterator[tuple[Path, str]]:
        for base, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for name in names:
                yield Path(base) / name, name

    def package_scripts() -> dict[str, str]:
        try:
            data = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
        return scripts if isinstance(scripts, dict) else {}

    def has_node() -> bool:
        return (root / "package.json").exists()

    def has_python() -> bool:
        markers = ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "pytest.ini")
        return any((root / m).exists() for m in markers)

    def pytest_cmd() -> list[str] | None:
        if importlib.util.find_spec("pytest"):
            return [sys.executable, "-m", "pytest"]
        return ["pytest"] if shutil.which("pytest") else None

    def ruff_cmd() -> list[str] | None:
        if shutil.which("ruff"):
            return ["ruff"]
        return [sys.executable, "-m", "ruff"] if importlib.util.find_spec("ruff") else None

    def skipped(detail: str) -> Result:
        return {"status": "skipped", "detail": detail, "metrics": {}}

    # ---- observation tools ---------------------------------------------------------------

    @registry.tool(description="Detect which stacks (node, python) the project uses.")
    def detect_stack() -> Result:
        stacks = []
        if has_node():
            stacks.append("node")
        if has_python():
            stacks.append("python")
        return {"stacks": stacks}

    @registry.tool(description="Run the project's tests (npm test and/or pytest).")
    def run_tests() -> Result:
        runs: list[tuple[str, Result]] = []
        npm_test = package_scripts().get("test", "")
        if npm_test and "no test specified" not in npm_test:
            runs.append(("npm test", run(["npm", "test", "--silent"], timeout=600)))
        if has_python():
            cmd = pytest_cmd()
            has_py_tests = any(
                n.endswith(".py") and (n.startswith("test_") or n.endswith("_test.py"))
                for _, n in files()
            )
            if cmd and has_py_tests:
                runs.append(
                    ("pytest", run([*cmd, "-q", "--no-header", "-p", "no:cacheprovider"], 600))
                )

        notes: list[str] = []
        failed = passed = 0
        tails: list[str] = []
        for label, r in runs:
            if r["code"] == 127 or (label == "pytest" and r["code"] == 5):
                notes.append(f"{label}: nothing ran")
            elif r["code"] == 0:
                passed += 1
                notes.append(f"{label}: pass")
            else:
                failed += 1
                notes.append(f"{label}: fail")
                tails.append(f"[{label}]\n{tail(r)}")
        if not notes:
            return skipped("no test runner detected")
        if failed == 0 and passed == 0:
            return skipped("; ".join(notes))
        return {
            "status": "fail" if failed else "pass",
            "detail": "; ".join(notes),
            "metrics": {"output_tail": "\n".join(tails)} if tails else {},
        }

    def lint() -> Result:
        notes: list[str] = []
        issues = 0
        failed = ran = False
        if has_python() and (cmd := ruff_cmd()):
            r = run([*cmd, "check", "--output-format=concise", "--no-cache", "."])
            if r["code"] != 127:
                ran = True
                count = len(re.findall(r":\d+:\d+:", r["stdout"]))
                if r["code"] != 0:
                    failed = True
                    issues += count
                    notes.append(f"ruff: {count} issue(s)")
                else:
                    notes.append("ruff: clean")
        if "lint" in package_scripts():
            r = run(["npm", "run", "lint", "--silent"], timeout=300)
            if r["code"] != 127:
                ran = True
                failed = failed or r["code"] != 0
                notes.append(f"npm lint: {'fail' if r['code'] else 'clean'}")
        if not ran:
            return skipped("no linter detected")
        return {
            "status": "fail" if failed else "pass",
            "detail": "; ".join(notes),
            "metrics": {"issues": issues} if issues else {},
        }

    registry.tool(description="Run linters (ruff and/or npm run lint).", name="run_lint")(lint)

    @registry.tool(description="List the most-changed files from git history.")
    def git_churn(days: int = 14, top: int = 15) -> Result:
        log = run(["git", "log", f"--since={days}.days.ago", "--no-merges",
                   "--name-only", "--pretty=format:"])  # fmt: skip
        if log["code"] != 0:
            return {"status": "skipped", "detail": tail(log, 2), "commits": 0, "files": []}
        count = run(
            ["git", "rev-list", "--count", "--no-merges", f"--since={days}.days.ago", "HEAD"]
        )
        counts = Counter(
            line.strip()
            for line in log["stdout"].splitlines()
            if line.strip() and Path(line.strip()).name not in _LOCKFILES
        )
        ranked = [{"path": p, "commits": n} for p, n in counts.most_common(top)]
        commits = int(count["stdout"].strip() or 0) if count["code"] == 0 else 0
        return {"status": "pass", "detail": f"{commits} commit(s) in {days} days",
                "commits": commits, "files": ranked}  # fmt: skip

    @registry.tool(description="Count outdated dependencies (npm outdated, pip list --outdated).")
    def dependency_drift() -> Result:
        outdated: list[str] = []
        checked = False
        if has_node() and (root / "node_modules").is_dir():
            r = run(["npm", "outdated", "--json"], timeout=60)
            if r["code"] in (0, 1) and r["stdout"].strip():
                try:
                    data = json.loads(r["stdout"])
                except ValueError:
                    data = None
                if isinstance(data, dict) and "error" not in data:
                    checked = True
                    outdated += [f"npm:{name}" for name in data]
        # pip only knows about an environment, so query it only inside a virtualenv.
        in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
        if has_python() and in_venv:
            r = run([sys.executable, "-m", "pip", "list", "--outdated", "--format=json"], 60)
            if r["code"] == 0:
                try:
                    rows = json.loads(r["stdout"])
                except ValueError:
                    rows = []
                checked = True
                outdated += [f"pip:{row['name']}" for row in rows if "name" in row]
        if not checked:
            return skipped("could not query package registries")
        return {
            "status": "warn" if outdated else "pass",
            "detail": f"{len(outdated)} outdated" if outdated else "up to date",
            "metrics": {"outdated": len(outdated), "packages": outdated[:20]},
        }

    @registry.tool(description="Count TODO, FIXME, HACK, and XXX markers per source file.")
    def todo_scan() -> Result:
        by_file: dict[str, int] = {}
        for path, name in files():
            if Path(name).suffix not in _SOURCE_SUFFIXES:
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                hits = len(_MARKERS.findall(path.read_text(encoding="utf-8", errors="ignore")))
            except OSError:
                continue
            if hits:
                by_file[path.relative_to(root).as_posix()] = hits
        return {"total": sum(by_file.values()), "by_file": by_file}

    # ---- action tools --------------------------------------------------------------------

    @registry.tool(
        description="Apply safe autofixes (ruff --fix, npm run lint -- --fix), then re-lint.",
        mutating=True,
    )
    def lint_fix() -> Result:
        if has_python() and (cmd := ruff_cmd()):
            run([*cmd, "check", "--fix", "--no-cache", "--quiet", "."])
        if "lint" in package_scripts():
            run(["npm", "run", "lint", "--silent", "--", "--fix"], timeout=300)
        result = lint()
        stat = run(["git", "diff", "--stat"])
        if stat["code"] == 0 and stat["stdout"].strip():
            result["metrics"] = {**result["metrics"], "diff_stat": stat["stdout"].strip()}
        result["detail"] = f"after autofix: {result['detail']}"
        return result

    @registry.tool(description="Write a markdown report into the .triad state directory.")
    def write_report(filename: str, content: str) -> Result:
        config.state_dir.mkdir(parents=True, exist_ok=True)
        target = config.state_dir / Path(filename).name  # .name strips any directory parts
        target.write_text(content, encoding="utf-8")
        return {"path": str(target)}

    return registry

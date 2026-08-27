"""PhaseG-B15 HARNESS generator. Generation is gated by Phase B cache."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .cli_hub_service import CliHubService, software_id

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = REPO_ROOT / "docs" / "agents" / "harness"
HARNESS_MD = HARNESS_DIR / "HARNESS.md"
HARNESS_LICENSE = HARNESS_DIR / "LICENSE"
SKILLS_DIR = Path(__file__).resolve().parent / "skills" / "harness"
CACHE_BASELINE = REPO_ROOT / "evals" / "baselines" / "cache-hit-rate.json"
PHASE_B_HIT_RATE_FLOOR = 99.0
STAGES = (
    "analyze",
    "design",
    "implement",
    "plan-tests",
    "write-tests",
    "document",
    "publish",
)
COMMANDS = ("refine", "validate")


class HarnessError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def phase_b_cache_status(path: Path | None = None) -> dict[str, Any]:
    """Honest Phase B §10 gate. Does not invent a 99% hit rate."""
    baseline = path or CACHE_BASELINE
    if not baseline.is_file():
        return {
            "landed": False,
            "error_code": "BLOCKED_PREREQUISITE",
            "reason": "Phase B cache baseline missing",
            "source": str(baseline),
            "floor": PHASE_B_HIT_RATE_FLOOR,
        }
    try:
        data = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "landed": False,
            "error_code": "BLOCKED_PREREQUISITE",
            "reason": f"Phase B cache baseline unreadable: {exc}",
            "source": str(baseline),
            "floor": PHASE_B_HIT_RATE_FLOOR,
        }
    raw = data.get("hit_rate")
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        rate = 0.0
    if 0.0 <= rate <= 1.0:
        rate *= 100.0
    landed = rate >= PHASE_B_HIT_RATE_FLOOR
    return {
        "landed": landed,
        "error_code": None if landed else "BLOCKED_PREREQUISITE",
        "reason": None if landed else f"Phase B hit_rate {rate} < {PHASE_B_HIT_RATE_FLOOR}",
        "hit_rate": rate,
        "source": str(baseline),
        "floor": PHASE_B_HIT_RATE_FLOOR,
        "baseline": data,
    }


class HarnessService:
    def __init__(self, hub: CliHubService | None = None, skills_dir: Path | None = None) -> None:
        self.hub = hub or CliHubService()
        self.skills_dir = skills_dir or SKILLS_DIR

    def vendor_status(self) -> dict[str, Any]:
        text = HARNESS_MD.read_text(encoding="utf-8") if HARNESS_MD.is_file() else ""
        license_text = HARNESS_LICENSE.read_text(encoding="utf-8") if HARNESS_LICENSE.is_file() else ""
        return {
            "harness_md": str(HARNESS_MD),
            "present": HARNESS_MD.is_file(),
            "has_apache": "Apache-2.0" in text or "Apache License" in license_text,
            "has_copyright": "Copyright" in license_text or "HKUDS" in text,
            "license_path": str(HARNESS_LICENSE),
            "bytes": len(text.encode("utf-8")),
        }

    def list_skills(self) -> dict[str, Any]:
        rows = []
        for name in (*STAGES, *COMMANDS):
            path = self.skills_dir / name / "SKILL.md"
            rows.append(
                {
                    "name": name,
                    "path": str(path),
                    "kind": "stage" if name in STAGES else "command",
                    "subtask": True,
                    "present": path.is_file(),
                }
            )
        return {"skills": rows, "stages": list(STAGES), "commands": list(COMMANDS)}

    def trigger(self, stage: str) -> dict[str, Any]:
        name = (stage or "").strip().lstrip("/")
        path = self.skills_dir / name / "SKILL.md"
        if not path.is_file():
            raise HarnessError("HARNESS_SKILL_MISSING", f"skill template missing: {name}")
        return {
            "ok": True,
            "stage": name,
            "subtask": True,
            "path": str(path),
            "text": path.read_text(encoding="utf-8"),
        }

    def validate(self, name: str | None = None) -> dict[str, Any]:
        vendor = self.vendor_status()
        skills = self.list_skills()
        missing = [row["name"] for row in skills["skills"] if not row["present"]]
        vendor_ok = vendor["present"] and vendor["has_apache"] and not missing
        gate = phase_b_cache_status()
        return {
            "ok": bool(vendor_ok and gate["landed"]),
            "vendor_ok": vendor_ok,
            "command": "validate",
            "name": name,
            "vendor": vendor,
            "missing_skills": missing,
            "cache": gate,
            "error_code": None if gate["landed"] else "BLOCKED_PREREQUISITE",
        }

    def generate(self, name: str, *, dest: Path | None = None, has_source: bool = True) -> dict[str, Any]:
        gate = phase_b_cache_status()
        if not gate["landed"]:
            self.hub.record_generate_failure(
                name,
                "generate",
                gate["reason"] or "BLOCKED_PREREQUISITE",
                next_step="refine",
            )
            return {
                "ok": False,
                "error_code": "BLOCKED_PREREQUISITE",
                "id": software_id(name),
                "cache": gate,
            }
        dest = dest or Path("generated-" + software_id(name)[4:])
        stages = [self.trigger(stage)["stage"] for stage in STAGES]
        first = self._emit_package(name, dest / "generate")
        refined = self.refine(name, dest=dest / "refine", reason="post-generate HARNESS refine")
        if not refined.get("ok"):
            closed = self.handwritten_wrapper(name, dest / "wrapper")
            ladder = "handwritten-wrapper"
        else:
            closed = refined.get("closed_loop") or first
            ladder = "refine"
        return {
            "ok": True,
            "error_code": None,
            "id": software_id(name),
            "cache": gate,
            "action": "generate",
            "stages": stages,
            "ladder": ladder,
            "closed_loop": closed,
        }

    def refine(self, name: str, reason: str = "quality below HARNESS", dest: Path | None = None) -> dict[str, Any]:
        gate = phase_b_cache_status()
        if not gate["landed"]:
            self.hub.record_generate_failure(name, "refine", gate["reason"] or "BLOCKED_PREREQUISITE")
            return {
                "ok": False,
                "error_code": "BLOCKED_PREREQUISITE",
                "id": software_id(name),
                "cache": gate,
                "command": "refine",
            }
        dest = dest or Path("refined-" + software_id(name)[4:])
        emitted = self._emit_package(name, dest, refined=True)
        validated = self.validate(name)
        if not validated.get("vendor_ok"):
            self.hub.record_generate_failure(name, "refine", reason)
            return {"ok": False, "command": "refine", "id": software_id(name), "cache": gate, "validate": validated}
        closed = self._install_launch(name, dest, emitted["module"])
        return {
            "ok": True,
            "command": "refine",
            "id": software_id(name),
            "cache": gate,
            "closed_loop": closed,
            "validate": validated,
        }

    def _emit_package(self, name: str, dest: Path, *, refined: bool = False) -> dict[str, Any]:
        sid = software_id(name)
        module = sid[4:].replace("-", "_")
        src = dest / "src" / module
        src.mkdir(parents=True, exist_ok=True)
        version = "0.1.1" if refined else "0.1.0"
        label = "harness-refined" if refined else "harness-wrapper"
        (src / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
        (src / "__main__.py").write_text(
            "import json, sys\n"
            f"print('{label}', ' '.join(sys.argv[1:]), flush=True)\n"
            "if '--json' in sys.argv:\n"
            f"    print(json.dumps({{'ok': True, 'refined': {str(refined)}}}), flush=True)\n",
            encoding="utf-8",
        )
        (dest / "pyproject.toml").write_text(
            f'[project]\nname = "{module}"\nversion = "{version}"\n',
            encoding="utf-8",
        )
        return {"id": sid, "module": module, "dest": dest, "version": version, "refined": refined}

    def _install_launch(self, name: str, dest: Path, module: str) -> dict[str, Any]:
        sid = software_id(name)
        spec = {
            "source": "self-generated",
            "module": module,
            "schema": {"name": sid},
            "install": {"kind": "local", "path": str(dest)},
        }
        self.hub.register_local(sid, spec)
        try:
            self.hub.uninstall(sid)
        except Exception:
            pass
        installed = self.hub.install(sid, source="self-generated")
        launched = self.hub.launch(sid, ["ok", "--json"])
        return {"ok": True, "id": sid, "source": "self-generated", "installed": installed, "launched": launched}

    def handwritten_wrapper(self, name: str, dest: Path) -> dict[str, Any]:
        """C-E fallback: emit a local wrapper and install/launch via B14."""
        gate = phase_b_cache_status()
        if not gate["landed"]:
            self.hub.record_generate_failure(
                name,
                "handwritten-wrapper",
                gate["reason"] or "BLOCKED_PREREQUISITE",
            )
            return {
                "ok": False,
                "error_code": "BLOCKED_PREREQUISITE",
                "id": software_id(name),
                "ladder": "handwritten-wrapper",
                "cache": gate,
            }
        emitted = self._emit_package(name, dest, refined=False)
        closed = self._install_launch(name, dest, emitted["module"])
        self.hub.record_generate_failure(name, "handwritten-wrapper", "C-E fallback after generate/refine")
        return {**closed, "ladder": "handwritten-wrapper", "version": emitted["version"], "cache": gate}

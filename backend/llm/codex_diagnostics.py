from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import config


SENSITIVE_KEY_RE = ("token", "secret", "api_key", "apikey", "access_token", "refresh_token", "openai_api_key")
ENV_NAMES = [
    "OPENAI_API_KEY",
    "CODEX_ACCESS_TOKEN",
    "CODEX_HOME",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT",
]


def env_presence() -> dict[str, bool]:
    return {name: bool(os.environ.get(name)) for name in ENV_NAMES}


def codex_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    if config.DISABLE_OPENAI_API:
        for name in ["OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT"]:
            env.pop(name, None)
    return env


def find_codex_path(command: str | None = None) -> str:
    return shutil.which(command or config.CODEX_CLI_COMMAND) or ""


def inspect_auth_cache() -> dict[str, Any]:
    candidates = _auth_candidates()
    found_path = ""
    safe_keys: list[str] = []
    suspected = "unknown"
    for path in candidates:
        if not path.exists():
            continue
        found_path = str(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            safe_keys = [_safe_key(key) for key in payload.keys() if _safe_key(key)]
            suspected = _suspected_auth_mode(payload)
        except Exception:
            safe_keys = ["unreadable_json"]
            suspected = "unknown"
        break
    return {
        "auth_cache_found": bool(found_path),
        "auth_cache_path": found_path or None,
        "auth_cache_top_level_keys": safe_keys,
        "suspected_auth_mode": suspected,
    }


def codex_health(run_text: bool = False, run_vision: bool = False, timeout_seconds: int | None = None) -> dict[str, Any]:
    timeout_seconds = timeout_seconds or config.CODEX_PROBE_TIMEOUT_SECONDS
    env = env_presence()
    codex_path = find_codex_path()
    auth = inspect_auth_cache()
    probe_cwd = probe_workspace()
    result: dict[str, Any] = {
        "codex_found": bool(codex_path),
        "codex_path": codex_path,
        "codex_version": "",
        "llm_provider": config.LLM_PROVIDER,
        "disable_openai_api": config.DISABLE_OPENAI_API,
        "env_openai_api_key_present": env["OPENAI_API_KEY"],
        "env_codex_access_token_present": env["CODEX_ACCESS_TOKEN"],
        "codex_home": os.environ.get("CODEX_HOME") or None,
        **auth,
        "text_ok": False,
        "text_warning": "",
        "text_error_summary": "",
        "vision_ok": None,
        "vision_warning": "",
        "vision_error_summary": "",
        "probe_cwd": str(probe_cwd),
        "probe_command_summary": {},
        "timed_out_after_output": False,
        "recommendation": "",
    }
    if not codex_path:
        result["recommendation"] = "Codex CLI was not found on PATH. Confirm Codex is installed and available in the same environment as FastAPI."
        return result

    command = codex_path or config.CODEX_CLI_COMMAND
    version = _run_command([command, "--version"], "", timeout_seconds=timeout_seconds, cwd=probe_cwd)
    result["codex_version"] = (version.stdout or version.stderr).strip().splitlines()[0][:200] if (version.stdout or version.stderr) else ""

    if run_text:
        text_cmd = _probe_command(command, image_path=None)
        text = _run_command(
            text_cmd,
            "Reply with exactly OK.",
            timeout_seconds=timeout_seconds,
            cwd=probe_cwd,
        )
        text_ok, text_warning = _text_probe_status(text)
        result["text_ok"] = text_ok
        result["text_warning"] = text_warning
        result["text_error_summary"] = "" if text_ok else command_error_summary(text)
        result["timed_out_after_output"] = bool(result["timed_out_after_output"] or (text.returncode == 124 and text_ok))
        result["probe_command_summary"]["text"] = _command_summary(text_cmd)
    else:
        result["text_error_summary"] = "Text probe skipped by default. Call /api/codex/health?run_probes=true to run Codex exec probes."

    image_path = latest_vision_png()
    if not image_path:
        result["vision_ok"] = None
        result["vision_error_summary"] = "No PNG found under data/vision for a safe vision probe."
    elif run_vision:
        vision_cmd = _probe_command(command, image_path=image_path)
        vision = _run_command(
            vision_cmd,
            "Describe this image in one short sentence.",
            timeout_seconds=timeout_seconds,
            cwd=probe_cwd,
        )
        vision_ok, vision_warning = _vision_probe_status(vision)
        result["vision_ok"] = vision_ok
        result["vision_warning"] = vision_warning
        result["vision_error_summary"] = "" if vision_ok else command_error_summary(vision)
        result["timed_out_after_output"] = bool(result["timed_out_after_output"] or (vision.returncode == 124 and vision_ok))
        result["probe_command_summary"]["vision"] = _command_summary(vision_cmd)
    else:
        result["vision_ok"] = None
        result["vision_error_summary"] = "Vision probe skipped by default. Call /api/codex/health?run_probes=true to run Codex image probes."

    result["recommendation"] = _recommendation(result)
    return result


def latest_vision_png() -> Path | None:
    roots = [config.PDF_IMAGE_DIR, config.PDF_RENDERED_PAGE_DIR, config.VISION_DIR]
    candidates: list[Path] = []
    for root in roots:
        if root.exists():
            candidates.extend(path for path in root.rglob("*.png") if path.is_file())
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def probe_workspace() -> Path:
    path = config.DATA_DIR / "codex_probe_workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def command_error_summary(completed: subprocess.CompletedProcess[str]) -> str:
    return json.dumps(
        {
            "returncode": completed.returncode,
            "stderr": sanitize_text(completed.stderr or "", 2000),
            "stdout": sanitize_text(completed.stdout or "", 2000),
        },
        ensure_ascii=False,
    )


def runtime_error_payload(
    *,
    returncode: int,
    stdout: str,
    stderr: str,
    codex_path: str,
    image_paths: list[Path],
    env_openai_api_key_present: bool,
) -> str:
    auth = inspect_auth_cache()
    return json.dumps(
        {
            "returncode": returncode,
            "stderr": sanitize_text(stderr, 2000),
            "stdout": sanitize_text(stdout, 2000),
            "codex_path": codex_path,
            "image_paths": [_image_info(path) for path in image_paths],
            "env_openai_api_key_present": env_openai_api_key_present,
            "suspected_auth_mode": auth.get("suspected_auth_mode", "unknown"),
        },
        ensure_ascii=False,
    )


def sanitize_text(text: str, limit: int = 500) -> str:
    for secret in [config.OPENAI_API_KEY, config.DEEPSEEK_API_KEY, config.GEMINI_API_KEY, os.environ.get("CODEX_ACCESS_TOKEN", "")]:
        if secret:
            text = text.replace(secret, "[redacted]")
    for marker in ["\nuser\n", "\nUser task:\n", "\nSYSTEM:\n", "\nUSER:\n"]:
        if marker in text:
            text = text.split(marker, 1)[0] + "\n[prompt omitted]"
    lines = []
    for line in text.splitlines():
        if line.startswith("User task:") or line.startswith("SYSTEM:") or line.startswith("USER:"):
            lines.append("[prompt omitted]")
            break
        lines.append(line)
    return "\n".join(lines)[:limit]


def _run_command(args: list[str], stdin: str, timeout_seconds: int, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = _command_for_platform(args)
    prompt = stdin if stdin.endswith("\n") else f"{stdin}\n"
    try:
        return subprocess.run(
            command,
            cwd=str(cwd or config.ROOT_DIR),
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
            env=codex_subprocess_env(),
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=command,
            returncode=124,
            stdout=_decode_timeout_payload(exc.stdout),
            stderr=f"{_decode_timeout_payload(exc.stderr)}\nTimed out after {timeout_seconds}s.",
        )
    except Exception as exc:
        return subprocess.CompletedProcess(args=command, returncode=127, stdout="", stderr=sanitize_text(str(exc), 500))


def _command_for_platform(args: list[str]) -> list[str]:
    if os.name == "nt" and Path(args[0]).suffix.lower() not in {".exe", ".com"}:
        return ["cmd.exe", "/d", "/c", *args]
    return args


def _probe_command(command: str, image_path: Path | None) -> list[str]:
    args = [
        command,
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
    ]
    if config.CODEX_PROBE_MODEL:
        args.extend(["--model", config.CODEX_PROBE_MODEL])
    if image_path:
        args.extend(["--image", str(image_path)])
    args.append("-")
    return args


def _command_summary(command: list[str]) -> list[str]:
    summary: list[str] = []
    skip_next = False
    for part in command:
        if skip_next:
            summary.append("<value>")
            skip_next = False
            continue
        summary.append(Path(part).name if part.lower().endswith(("codex", "codex.cmd", "codex.exe")) else part)
        if part in {"--image", "--model"}:
            skip_next = True
    return summary


def _text_probe_status(completed: subprocess.CompletedProcess[str]) -> tuple[bool, str]:
    stdout = completed.stdout or ""
    if completed.returncode == 0 and stdout.strip():
        return True, ""
    if completed.returncode == 124 and re.search(r"\bOK\b", stdout, re.I):
        return True, "Codex produced output but process timed out after output."
    return False, ""


def _vision_probe_status(completed: subprocess.CompletedProcess[str]) -> tuple[bool, str]:
    stdout = completed.stdout or ""
    if completed.returncode == 0 and _looks_like_vision_output(stdout):
        return True, ""
    if completed.returncode == 124 and _looks_like_vision_output(stdout):
        return True, "Codex produced output but process timed out after output."
    return False, ""


def _looks_like_vision_output(stdout: str) -> bool:
    text = sanitize_text(stdout, 2000).strip()
    if not text:
        return False
    noise_prefixes = ("openai codex", "--------", "workdir:", "model:", "provider:", "approval:", "sandbox:", "reasoning", "session id:", "user")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    useful = [line for line in lines if not line.lower().startswith(noise_prefixes) and "describe this image" not in line.lower()]
    return any(len(line) >= 12 and any(ch.isalpha() for ch in line) for line in useful)


def _decode_timeout_payload(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _auth_candidates() -> list[Path]:
    candidates: list[Path] = []
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        candidates.append(Path(userprofile) / ".codex" / "auth.json")
    candidates.append(Path.home() / ".codex" / "auth.json")
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        candidates.append(Path(codex_home) / "auth.json")
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _safe_key(key: str) -> str:
    lowered = key.lower()
    if any(token in lowered for token in SENSITIVE_KEY_RE):
        return ""
    return key


def _suspected_auth_mode(payload: Any) -> str:
    if isinstance(payload, dict):
        auth_mode = str(payload.get("auth_mode") or payload.get("mode") or "").lower()
        if "chatgpt" in auth_mode or "plus" in auth_mode:
            return "chatgpt"
        if "api" in auth_mode or "key" in auth_mode:
            return "api_key"
        keys = _all_keys(payload)
        if any("api_key" in key or "apikey" in key or key == "openai_api_key" for key in keys):
            return "api_key"
        if any("chatgpt" in key for key in keys):
            return "chatgpt"
    return "unknown"


def _all_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key).lower())
            keys.update(_all_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_all_keys(item))
    return keys


def _image_info(path: Path) -> dict[str, Any]:
    try:
        resolved = path.resolve()
        return {
            "path": str(resolved),
            "exists": resolved.exists(),
            "size_bytes": resolved.stat().st_size if resolved.exists() else 0,
            "suffix": resolved.suffix.lower(),
        }
    except Exception:
        return {"path": str(path), "exists": False, "size_bytes": 0, "suffix": path.suffix.lower()}


def _recommendation(result: dict[str, Any]) -> str:
    combined_error = " ".join(
        str(result.get(key) or "")
        for key in ["text_error_summary", "vision_error_summary"]
    )
    if re.search(r"401|unauthorized|missing bearer", combined_error, re.I):
        return "Codex returned an authentication error. Re-run codex login with ChatGPT/Plus and avoid API key login."
    if re.search(r"not inside a trusted directory", combined_error, re.I):
        return "Codex reported an untrusted directory. Ensure probes include --skip-git-repo-check or run from a trusted workspace."
    if "Timed out" in combined_error and not result.get("timed_out_after_output"):
        return "Codex probe timed out without useful stdout. Check CODEX_PROBE_TIMEOUT_SECONDS, probe cwd, and network latency."
    if result.get("env_openai_api_key_present"):
        return "OPENAI_API_KEY is present in the backend process. It is stripped from Codex subprocesses when DISABLE_OPENAI_API=true, but clearing it keeps diagnostics unambiguous."
    if result.get("suspected_auth_mode") == "api_key":
        return "Codex auth cache looks like API key login. Back up auth.json, clear it manually, run codex, and choose ChatGPT/Plus login."
    if result.get("text_ok") and result.get("vision_ok") is False:
        return "Codex text works but vision fails. Test codex --image manually with the same PNG and inspect local Codex login/capability state."
    if not result.get("text_ok"):
        return "Codex text probe failed without an authentication signature. Compare the probe command summary with a manual codex exec run."
    return "Codex local runtime probes look usable."

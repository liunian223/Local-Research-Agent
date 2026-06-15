from __future__ import annotations

import subprocess
import tempfile
import os
from pathlib import Path
from typing import Optional

import config
from deepseek_client import LLMResult


class CodexCliClient:
    def generate_text(
        self,
        prompt: str,
        system: str = "",
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: Optional[int] = None,
        image_paths: Optional[list[str]] = None,
    ) -> LLMResult:
        del temperature, max_output_tokens
        full_prompt = _codex_prompt(prompt, system)
        fd, raw_output_path = tempfile.mkstemp(prefix="local_research_agent_codex_", suffix=".txt")
        os.close(fd)
        output_path = Path(raw_output_path)
        codex_args = [
            config.CODEX_CLI_COMMAND,
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--output-last-message",
            str(output_path),
        ]
        chosen_model = model or config.CODEX_CLI_MODEL
        if chosen_model:
            codex_args.extend(["--model", chosen_model])
        valid_images = _valid_image_paths(image_paths or [])
        for image_path in valid_images:
            codex_args.extend(["--image", str(image_path)])
        codex_args.append("-")
        command = _command_for_platform(codex_args)
        try:
            completed = subprocess.run(
                command,
                cwd=str(config.ROOT_DIR),
                input=full_prompt,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=config.CODEX_CLI_TIMEOUT_SECONDS,
                check=False,
            )
            if output_path.exists():
                content = output_path.read_text(encoding="utf-8", errors="replace").strip()
            else:
                content = (completed.stdout or "").strip()
            if completed.returncode == 0 and content:
                return LLMResult(ok=True, content=content, model=_codex_model_name(chosen_model), usage_summary=f"provider=codex_cli; images={len(valid_images)}")
            error = "\n".join(part for part in [completed.stderr.strip(), completed.stdout.strip()] if part)
            return LLMResult(ok=False, content="", model=_codex_model_name(chosen_model), error=_safe_error(error or f"codex exec exited with {completed.returncode}"))
        except Exception as exc:
            return LLMResult(ok=False, content="", model=_codex_model_name(chosen_model), error=_safe_error(str(exc)))
        finally:
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass


def _codex_prompt(prompt: str, system: str = "") -> str:
    instructions = [
        "You are being called as an LLM provider for a local RAG application.",
        "If image attachments are present, inspect them together with the supplied RAG evidence.",
        "Answer the user's task directly. Do not edit files, run commands, or mention Codex internals.",
    ]
    if system:
        instructions.append(f"System instructions:\n{system}")
    instructions.append(f"User task:\n{prompt}")
    return "\n\n".join(instructions)


def _codex_model_name(model: str) -> str:
    return f"codex_cli:{model or 'default'}"


def _command_for_platform(args: list[str]) -> list[str]:
    if os.name == "nt":
        return ["cmd.exe", "/d", "/c", *args]
    return args


def _valid_image_paths(paths: list[str]) -> list[Path]:
    valid: list[Path] = []
    seen: set[str] = set()
    for value in paths:
        path = Path(value)
        if not path.is_absolute():
            path = config.ROOT_DIR / path
        try:
            resolved = path.resolve()
        except Exception:
            continue
        if not resolved.exists() or not resolved.is_file():
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        valid.append(resolved)
    return valid


def _safe_error(error: str) -> str:
    return error[:800]

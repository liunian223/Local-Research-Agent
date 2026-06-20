from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

import config
from llm.base import LLMClient, LLMClientError
from llm.codex_diagnostics import codex_subprocess_env, find_codex_path, runtime_error_payload, sanitize_text


class CodexRuntimeClient(LLMClient):
    def __init__(
        self,
        *,
        command: str | None = None,
        text_model: str | None = None,
        vision_model: str | None = None,
        sandbox: str | None = None,
        timeout_seconds: int | None = None,
        max_concurrency: int | None = None,
    ) -> None:
        self.command = command or config.CODEX_CLI_COMMAND
        self.text_model = text_model if text_model is not None else config.CODEX_MODEL_TEXT
        self.vision_model = vision_model if vision_model is not None else config.CODEX_MODEL_VISION
        self.sandbox = _sandbox_value(sandbox or config.CODEX_SANDBOX)
        self.timeout_seconds = timeout_seconds or config.CODEX_TIMEOUT_SECONDS
        self._semaphore = threading.BoundedSemaphore(max(1, max_concurrency or config.CODEX_MAX_CONCURRENCY))

    async def chat(self, messages: list[dict[str, str]], task_type: str = "chat", temperature: float = 0.2) -> str:
        del temperature
        prompt = _prompt_from_messages(messages)
        return await self._run_codex(prompt, model=self.text_model, task_type=task_type, image_paths=[])

    async def vision_chat(self, prompt: str, image_paths: list[str], task_type: str = "vision") -> str:
        valid_images = _valid_vision_paths(image_paths)
        if not valid_images:
            raise LLMClientError("No valid project-local vision images were provided.", provider="codex", task_type=task_type)
        return await self._run_codex(prompt, model=self.vision_model, task_type=task_type, image_paths=valid_images)

    def chat_sync(self, messages: list[dict[str, str]], task_type: str = "chat", temperature: float = 0.2) -> str:
        return _run_coro_blocking(self.chat(messages, task_type=task_type, temperature=temperature))

    def vision_chat_sync(self, prompt: str, image_paths: list[str], task_type: str = "vision") -> str:
        return _run_coro_blocking(self.vision_chat(prompt, image_paths, task_type=task_type))

    async def _run_codex(self, prompt: str, *, model: str, task_type: str, image_paths: list[Path]) -> str:
        await asyncio.to_thread(self._semaphore.acquire)
        try:
            return await asyncio.to_thread(self._run_codex_blocking, prompt, model, task_type, image_paths)
        finally:
            self._semaphore.release()

    def _run_codex_blocking(self, prompt: str, model: str, task_type: str, image_paths: list[Path]) -> str:
        output_path = _temp_output_path()
        codex_path = find_codex_path(self.command) or self.command
        args = [
            codex_path,
            "exec",
            "--ephemeral",
            "--sandbox",
            self.sandbox,
            "--skip-git-repo-check",
            "--output-last-message",
            str(output_path),
        ]
        if model:
            args.extend(["--model", model])
        for image_path in image_paths:
            args.extend(["--image", str(image_path)])
        args.append("-")
        command = _command_for_platform(args)
        codex_env = codex_subprocess_env()
        try:
            completed = subprocess.run(
                command,
                cwd=str(config.ROOT_DIR),
                env=codex_env,
                input=_stdin_prompt(_codex_provider_prompt(prompt, bool(image_paths))),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
            content = output_path.read_text(encoding="utf-8", errors="replace").strip() if output_path.exists() else (completed.stdout or "").strip()
            if completed.returncode == 0 and content:
                return content
            error = runtime_error_payload(
                returncode=completed.returncode,
                stderr=completed.stderr or "",
                stdout=completed.stdout or "",
                codex_path=codex_path,
                image_paths=image_paths,
                env_openai_api_key_present=bool(codex_env.get("OPENAI_API_KEY")),
            )
            raise LLMClientError(error, provider="codex", task_type=task_type, retryable=True)
        except subprocess.TimeoutExpired as exc:
            content = output_path.read_text(encoding="utf-8", errors="replace").strip() if output_path.exists() else ""
            if content:
                return content
            stdout = _decode_timeout_payload(exc.stdout)
            stderr = _decode_timeout_payload(exc.stderr)
            error = runtime_error_payload(
                returncode=124,
                stderr=f"{stderr}\nTimed out after {self.timeout_seconds}s.",
                stdout=stdout,
                codex_path=codex_path,
                image_paths=image_paths,
                env_openai_api_key_present=bool(codex_env.get("OPENAI_API_KEY")),
            )
            raise LLMClientError(error, provider="codex", task_type=task_type, retryable=True) from exc
        except LLMClientError:
            raise
        except Exception as exc:
            raise LLMClientError(_safe_error(str(exc)), provider="codex", task_type=task_type, retryable=True) from exc
        finally:
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass


def _prompt_from_messages(messages: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for message in messages:
        role = message.get("role", "user")
        content = (message.get("content") or "")[: config.MAX_CONTEXT_CHARS_PER_LLM_CALL]
        parts.append(f"{role.upper()}:\n{content}")
    return "\n\n".join(parts)


def _codex_provider_prompt(prompt: str, has_images: bool) -> str:
    instructions = [
        "You are being called as a local LLM provider for Local Research Agent.",
        "Do not edit files, run commands, or mention Codex internals.",
        "Use only the supplied prompt, local RAG evidence, and attached images.",
        "If evidence is insufficient or an image is unclear, say so clearly.",
    ]
    if has_images:
        instructions.append("Image attachments come only from the uploaded PDF or rendered PDF pages.")
    instructions.append(f"User task:\n{prompt[: config.MAX_CONTEXT_CHARS_PER_LLM_CALL]}")
    return "\n\n".join(instructions)


def _stdin_prompt(prompt: str) -> str:
    return prompt if prompt.endswith("\n") else f"{prompt}\n"


def _valid_vision_paths(paths: list[str]) -> list[Path]:
    roots = [config.PDF_IMAGE_DIR.resolve(), config.PDF_RENDERED_PAGE_DIR.resolve()]
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
        if not any(resolved.is_relative_to(root) for root in roots):
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        valid.append(resolved)
    return valid[: config.MAX_VISION_IMAGES_PER_CALL]


def _sandbox_value(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    return "read-only" if normalized in {"read-only", "readonly"} else normalized


def _command_for_platform(args: list[str]) -> list[str]:
    if os.name == "nt" and Path(args[0]).suffix.lower() not in {".exe", ".com"}:
        return ["cmd.exe", "/d", "/c", *args]
    return args


def _temp_output_path() -> Path:
    fd, raw_output_path = tempfile.mkstemp(prefix="local_research_agent_codex_", suffix=".txt")
    os.close(fd)
    return Path(raw_output_path)


def _run_coro_blocking(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise LLMClientError("Synchronous Codex call cannot run inside an active event loop.", provider="codex", task_type="sync_bridge")


def _safe_error(error: str) -> str:
    return sanitize_text(error, 500)


def _decode_timeout_payload(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)

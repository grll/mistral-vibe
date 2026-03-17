from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from enum import StrEnum, auto
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class HookEvent(StrEnum):
    USER_PROMPT_SUBMIT = auto()
    NOTIFICATION = auto()
    POST_TOOL_USE = auto()
    STOP = auto()


class HookEntry(BaseModel):
    matcher: str = ""
    command: str

    def matches(self, tool_name: str) -> bool:
        if not self.matcher:
            return True
        return bool(re.search(self.matcher, tool_name))


class HooksConfig(BaseModel):
    UserPromptSubmit: list[HookEntry] = Field(default_factory=list)
    Notification: list[HookEntry] = Field(default_factory=list)
    PostToolUse: list[HookEntry] = Field(default_factory=list)
    Stop: list[HookEntry] = Field(default_factory=list)


async def run_hook(command: str, context: dict[str, Any], timeout: float = 30.0) -> None:
    env = {**os.environ, "VIBE_PROJECT_DIR": str(Path.cwd())}
    stdin_data = json.dumps(context).encode()

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(Path.cwd()),
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_data), timeout=timeout
        )
        if proc.returncode != 0:
            logger.warning(
                "Hook %r exited with code %d: %s",
                command,
                proc.returncode,
                stderr.decode(errors="replace").strip(),
            )
    except asyncio.TimeoutError:
        logger.warning("Hook %r timed out after %.0fs", command, timeout)
    except Exception:
        logger.warning("Hook %r failed", command, exc_info=True)


async def run_hooks(
    hooks_config: HooksConfig,
    event: HookEvent,
    context: dict[str, Any],
) -> None:
    event_to_entries: dict[HookEvent, list[HookEntry]] = {
        HookEvent.USER_PROMPT_SUBMIT: hooks_config.UserPromptSubmit,
        HookEvent.NOTIFICATION: hooks_config.Notification,
        HookEvent.POST_TOOL_USE: hooks_config.PostToolUse,
        HookEvent.STOP: hooks_config.Stop,
    }
    entries = event_to_entries.get(event, [])
    if not entries:
        return

    match_key = {
        HookEvent.POST_TOOL_USE: "tool_name",
        HookEvent.NOTIFICATION: "type",
    }.get(event, "")
    match_value = context.get(match_key, "") if match_key else ""

    for entry in entries:
        if match_key and not entry.matches(match_value):
            continue
        await run_hook(entry.command, context)

"""Streaming helpers shared by LangGraph resource flows."""

from __future__ import annotations

import logging

from langgraph.config import get_stream_writer

logger = logging.getLogger(__name__)

TEXT_STREAM_CHUNK_SIZE = 80


def iter_stream_text_chunks(text: str, chunk_size: int = TEXT_STREAM_CHUNK_SIZE):
    for start in range(0, len(text), chunk_size):
        yield text[start:start + chunk_size]


def push_text_stream(
    stream_writer,
    file_type: str,
    content: str,
    *,
    section_idx: int | None = None,
    section_title: str = "",
    total: int | None = None,
):
    if not stream_writer or not content:
        return

    meta = {
        "file_type": file_type,
        "section_idx": section_idx,
        "section_title": section_title,
        "total": total,
    }
    try:
        stream_writer({"type": "stream_text_start", **meta})
        cursor = 0
        for delta in iter_stream_text_chunks(str(content)):
            stream_writer({
                "type": "stream_text_delta",
                "delta": delta,
                "cursor": cursor,
                **meta,
            })
            cursor += len(delta)
        stream_writer({
            "type": "stream_text_done",
            "content": content,
            **meta,
        })
    except Exception as exc:
        if is_stream_context_error(exc):
            logger.debug(
                "[Text-Stream] 不在可运行的上下文中，已跳过 file_type=%s section=%s",
                file_type,
                section_idx,
            )
            return
        logger.exception("[Text-Stream] 推送失败 file_type=%s section=%s", file_type, section_idx)


def push_agent_event(
    stream_writer,
    agent_id: str,
    agent_name: str,
    phase: str,
    status: str,
    message: str,
    **extra,
):
    if not stream_writer:
        return
    try:
        stream_writer({
            "type": "agent_event",
            "agent_id": agent_id,
            "agent_name": agent_name,
            "phase": phase,
            "status": status,
            "message": message,
            **extra,
        })
    except Exception as exc:
        if is_stream_context_error(exc):
            logger.debug("[AgentFlow] 不在可运行的上下文中，已跳过 agent_id=%s", agent_id)
            return
        logger.exception("[AgentFlow] 推送失败 agent_id=%s", agent_id)


def is_stream_context_error(exc: Exception) -> bool:
    return isinstance(exc, RuntimeError) and "outside of a runnable context" in str(exc)


def safe_stream_writer():
    try:
        return get_stream_writer()
    except Exception:
        return None

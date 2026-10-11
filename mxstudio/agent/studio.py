"""«ابدأ هنا»: conversations with the Studio agent — text, reference images, previews, revisions.

Shared by the in-Studio chat (HTTP) and the MCP server, so both see the same uploads,
conversations and pending approvals. The model acts only through the typed tools; anything
irreversible becomes a pending approval that only a human in the Studio UI can decide.
"""
from __future__ import annotations

import secrets
import time

from mxstudio.agent.images import ImageRejected, for_model, verify_upload

HISTORY_IMAGES = 4  # how many earlier pictures stay in the model's context (newest first)


def add_reference(state, data: bytes, name: str = "", note: str = "") -> dict:
    """Store an uploaded design reference (original bytes, content-addressed) and its record."""
    facts = verify_upload(data)
    sha = state.workspace.put_bytes(data)
    body = {"sha": sha, "name": str(name)[:120], "note": str(note)[:500], "uploaded_at": time.time(), **facts}
    state.workspace.save("reference", sha[:16], body, {"original": sha}, note="uploaded by the operator")
    return body


def list_references(state, limit: int = 30) -> list[dict]:
    items = [state.workspace.get("reference", key)["body"] for key in state.workspace.keys("reference")]
    return sorted(items, key=lambda item: item.get("uploaded_at", 0), reverse=True)[:limit]


def model_image(state, sha: str) -> bytes | None:
    try:
        if not state.workspace.verify_blob(sha):
            return None
        return for_model(state.workspace.blob_path(sha).read_bytes())
    except (ValueError, ImageRejected, OSError):
        return None


# -- conversations -----------------------------------------------------------------
def new_conversation(state, title: str = "") -> str:
    conversation_id = secrets.token_hex(6)
    state.workspace.save("conversation", conversation_id, {"title": title[:120], "messages": [],
                                                           "created_at": time.time()}, note="new conversation")
    return conversation_id


def load_conversation(state, conversation_id: str) -> dict | None:
    record = state.workspace.get("conversation", conversation_id)
    return record["body"] if record else None


def list_conversations(state, limit: int = 20) -> list[dict]:
    out = []
    for key in state.workspace.keys("conversation"):
        body = state.workspace.get("conversation", key)["body"]
        out.append({"id": key, "title": body.get("title", ""), "updated_at": body.get("updated_at", 0),
                    "turns": sum(1 for m in body.get("messages", []) if m.get("role") == "user" and m.get("operator"))})
    return sorted(out, key=lambda c: c["updated_at"], reverse=True)[:limit]


def _history(state, messages: list[dict]) -> list[dict]:
    """Stored messages → model messages; only the newest HISTORY_IMAGES pictures are re-attached."""
    budget = HISTORY_IMAGES
    out: list[dict] = []
    for message in reversed(messages):
        item = {"role": message["role"], "content": message["content"]}
        shas = message.get("image_shas") or []
        if shas and budget > 0:
            pictures = [img for img in (model_image(state, sha) for sha in shas[:budget]) if img]
            budget -= len(pictures)
            if pictures:
                item["images"] = pictures
        out.append(item)
    return list(reversed(out))


def chat_turn(state, app, provider, conversation_id: str, text: str, reference_shas: list[str] | None = None) -> dict:
    """One operator turn: run the agent on the whole conversation, store it, return what the UI shows."""
    from mxstudio.agent import loop  # noqa: PLC0415
    from mxstudio.agent.manual import build_manual  # noqa: PLC0415

    conversation = load_conversation(state, conversation_id)
    if conversation is None:
        raise KeyError(conversation_id)
    shas = [sha for sha in (reference_shas or []) if state.workspace.verify_blob(sha)]
    images = [img for img in (model_image(state, sha) for sha in shas) if img]
    mode = state.settings.load()["agent"].get("mode", "suggest_only")
    task = text
    if shas:
        task += "\n\n[Uploaded reference images, by sha256 (use colour.from_art with reference=<sha>): " + \
                ", ".join(shas) + "]"
    if mode != "full":
        task = ("SUGGESTION-ONLY MODE: do not call any tool that changes state; reply with a plan and final.\n"
                + task)
    run = loop.run(state, provider, task, build_manual(state, app), history=_history(state, conversation["messages"]),
                   images=images)
    stored = []
    for index, message in enumerate(run.messages):
        item = {"role": message["role"], "content": message["content"]}
        if index == 0:
            item["operator"], item["image_shas"] = text, shas
            item["reply"], item["status"] = run.report, run.status
            if run.pending:
                item["pending_id"] = run.pending.get("pending_id")
        elif message.get("image_shas"):
            item["image_shas"] = list(message["image_shas"])
        stored.append(item)
    previews = [r["result"]["preview_sha"] for r in run.tool_results
                if r["ok"] and isinstance(r.get("result"), dict) and r["result"].get("preview_sha")]
    conversation["messages"] += stored
    conversation["updated_at"] = time.time()
    if not conversation.get("title"):
        conversation["title"] = text[:60]
    conversation.setdefault("previews", [])
    conversation["previews"] += previews
    state.workspace.save("conversation", conversation_id, conversation, note="chat turn")
    return {"conversation_id": conversation_id, "mode": mode, "status": run.status, "reply": run.report,
            "plan": run.plan, "pending": run.pending, "flags": run.flags,
            "tools": [{"tool": r["tool"], "ok": r["ok"], "code": r["code"]} for r in run.tool_results],
            "preview_sha": previews[-1] if previews else (conversation["previews"][-1]
                                                          if conversation["previews"] else None)}


def transcript(state, conversation_id: str) -> dict | None:
    """What the UI shows: the operator's words, the agent's final replies, pictures and previews."""
    conversation = load_conversation(state, conversation_id)
    if conversation is None:
        return None
    import json  # noqa: PLC0415
    shown: list[dict] = []
    reply: dict | None = None

    def close_turn():
        if reply and reply.get("text"):
            shown.append(reply)

    for message in conversation["messages"]:
        if message["role"] == "user" and message.get("operator") is not None:
            close_turn()
            shown.append({"who": "operator", "text": message["operator"], "image_shas": message.get("image_shas", [])})
            reply = {"who": "agent", "text": message.get("reply", ""), "status": message.get("status", ""),
                     "pending_id": message.get("pending_id")}
        elif message["role"] == "assistant":  # plans are shown as they were made; the turn's reply comes last
            try:
                move = json.loads(message["content"][message["content"].index("{"):message["content"].rindex("}") + 1])
            except ValueError:
                continue
            if "plan" in move:
                shown.append({"who": "agent", "plan": [str(s) for s in move["plan"]][:20]})
    close_turn()
    return {"id": conversation_id, "title": conversation.get("title", ""), "messages": shown,
            "previews": conversation.get("previews", [])}

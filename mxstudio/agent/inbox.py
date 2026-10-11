"""«الوارد» (inbox) and «طلبات Claude Desktop» (requests): how pictures and briefs reach Claude Desktop.

Why: a picture dropped into a Claude Desktop chat never reaches the Studio as a file (Claude cannot know the
attachment's path), and Claude Desktop has no API another program can call — the connection only goes
Claude Desktop → MCP → Studio. So the operator puts pictures in a fixed folder (drag & drop on «ابدأ هنا» or the
desktop shortcut) and, without an API key, writes the brief in the Studio; Claude Desktop then pulls both through
MCP tools (studio_inbox_list / studio_inbox_use / studio_requests_list / studio_request_claim / studio_request_done).

Rules: inbox names are plain file names inside the inbox (no paths, no traversal); only real pictures are used;
requests live in the app home (shared by the window and every MCP process, SQLite WAL + busy timeout).
"""
from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

PICTURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
STATUSES = ("new", "claimed", "done", "failed")


class InboxError(ValueError):
    def __init__(self, code: str, ar: str, en: str):
        super().__init__(en)
        self.code, self.ar, self.en = code, ar, en

    def as_dict(self) -> dict:
        return {"code": self.code, "ar": self.ar, "en": self.en}


# ------------------------------------------------------------------ inbox
def inbox_dir(workspace_root: Path) -> Path:
    folder = Path(workspace_root) / "inbox"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def safe_name(name: str) -> str:
    name = Path(str(name or "")).name.strip().strip(".")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)[:120]
    return name or "picture"


def save_to_inbox(workspace_root: Path, data: bytes, name: str) -> Path:
    """Store an uploaded picture in the inbox under a unique, time-ordered name."""
    from mxstudio.agent.images import verify_upload  # noqa: PLC0415 - raises ImageRejected for non-pictures
    verify_upload(data)
    clean = safe_name(name)
    stem, suffix = Path(clean).stem, (Path(clean).suffix.lower() or ".png")
    if suffix not in PICTURE_SUFFIXES:
        suffix = ".png"
    target = inbox_dir(workspace_root) / f"{time.strftime('%Y%m%d-%H%M%S')}_{stem}{suffix}"
    while target.exists():
        target = target.with_name(f"{target.stem}_{secrets.token_hex(2)}{suffix}")
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    return target


def _size(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image  # noqa: PLC0415
        with Image.open(path) as image:
            return image.size
    except Exception:  # noqa: BLE001 - a broken file is listed without a size
        return None


def list_inbox(workspace_root: Path, limit: int = 50) -> list[dict]:
    folder = inbox_dir(workspace_root)
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in PICTURE_SUFFIXES]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for path in files[:limit]:
        stat = path.stat()
        size = _size(path)
        out.append({"name": path.name, "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                    "modified_epoch": round(stat.st_mtime, 3), "bytes": stat.st_size,
                    "width": size[0] if size else None, "height": size[1] if size else None})
    return out


def inbox_file(workspace_root: Path, name: str) -> Path:
    """The inbox file called `name`; «latest»/«آخر صورة»/empty means the newest picture."""
    folder = inbox_dir(workspace_root)
    wanted = str(name or "").strip()
    if wanted.casefold() in {"", "latest", "last", "newest", "آخر صورة", "اخر صورة", "الأخيرة"}:
        items = list_inbox(workspace_root, 1)
        if not items:
            raise InboxError("INBOX_EMPTY", "مفيش صور في «الوارد» — اسحب صورة على «ابدأ هنا» الأول.",
                             "the inbox is empty")
        wanted = items[0]["name"]
    if Path(wanted).name != wanted or wanted in {".", ".."}:
        raise InboxError("BAD_NAME", "اسم الصورة لازم يكون اسم ملف بس.", "inbox names are plain file names")
    path = folder / wanted
    if not path.is_file() or path.resolve().parent != folder.resolve():
        raise InboxError("NOT_FOUND", f"مفيش صورة اسمها «{wanted}» في «الوارد».", f"no inbox picture named {wanted}")
    return path


# ------------------------------------------------------------------ requests prepared for Claude Desktop
class RequestStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, text TEXT NOT NULL, image_shas TEXT NOT NULL, inbox_names TEXT NOT NULL,
                created_at REAL NOT NULL, status TEXT NOT NULL, claimed_by TEXT, claimed_at REAL,
                story_key TEXT, preview_sha TEXT, done_at REAL, note TEXT)""")

    def _connect(self):
        from mxstudio.sqlite_util import connect  # noqa: PLC0415
        return connect(self.path, rows=True)

    @staticmethod
    def _row(row) -> dict:
        out = dict(row)
        out["image_shas"] = json.loads(out["image_shas"])
        out["inbox_names"] = json.loads(out["inbox_names"])
        return out

    def add(self, text: str, image_shas: list[str] | None = None, inbox_names: list[str] | None = None) -> dict:
        text = str(text or "").strip()[:8000]
        if not text and not image_shas:
            raise InboxError("EMPTY", "اكتب الطلب أو حط صورة.", "empty request")
        rid = f"r{time.strftime('%m%d')}-{secrets.token_hex(3)}"
        with self._connect() as db:
            db.execute("INSERT INTO requests (id, text, image_shas, inbox_names, created_at, status) "
                       "VALUES (?, ?, ?, ?, ?, 'new')",
                       (rid, text, json.dumps(list(image_shas or [])), json.dumps(list(inbox_names or [])), time.time()))
        return self.get(rid)

    def get(self, rid: str) -> dict:
        with self._connect() as db:
            row = db.execute("SELECT * FROM requests WHERE id = ?", (str(rid),)).fetchone()
        if row is None:
            raise InboxError("NOT_FOUND", f"مفيش طلب رقمه {rid}.", f"no request {rid}")
        return self._row(row)

    def list(self, status: str | None = None, limit: int = 50) -> list[dict]:
        with self._connect() as db:
            if status in STATUSES:
                rows = db.execute("SELECT * FROM requests WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                                  (status, limit)).fetchall()
            elif status == "open":
                rows = db.execute("SELECT * FROM requests WHERE status IN ('new', 'claimed') ORDER BY created_at "
                                  "LIMIT ?", (limit,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM requests ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def claim(self, rid: str, actor: str) -> dict:
        """new → claimed. A claimed request can be claimed again by the same or another session (a Claude Desktop
        chat that was closed must not leave the request stuck); done/failed ones cannot."""
        current = self.get(rid)
        if current["status"] in {"done", "failed"}:
            raise InboxError("ALREADY_DONE", f"الطلب {rid} اتنفّذ قبل كده.", f"request {rid} is already {current['status']}")
        with self._connect() as db:
            db.execute("UPDATE requests SET status = 'claimed', claimed_by = ?, claimed_at = ? WHERE id = ?",
                       (actor, time.time(), rid))
        return self.get(rid)

    def done(self, rid: str, story_key: str, preview_sha: str | None = None, ok: bool = True, note: str = "") -> dict:
        current = self.get(rid)
        if current["status"] == "done":
            raise InboxError("ALREADY_DONE", f"الطلب {rid} اتقفل قبل كده.", f"request {rid} is already done")
        with self._connect() as db:
            db.execute("UPDATE requests SET status = ?, story_key = ?, preview_sha = ?, done_at = ?, note = ? "
                       "WHERE id = ?", ("done" if ok else "failed", story_key, preview_sha, time.time(), note[:500], rid))
        return self.get(rid)

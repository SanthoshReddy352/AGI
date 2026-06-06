"""Track 6.2 — background filesystem indexer.

Walks the user's directories (Documents, Downloads, Desktop, Pictures,
Videos, Music) plus mounted external drives, and persists every file
found into `FileIndexStore`. The router uses the persisted index to
answer "where is the file called X" without re-walking the filesystem
on every turn.

Scope is intentionally narrow: user dirs and external mounts, not
system directories. Excludes hidden dirs, build artifacts, and VCS
metadata by default.

`watchdog` is an optional dependency — if available, `start_watcher()`
attaches an event-driven observer for real-time updates. If not, the
indexer runs a one-shot scan on startup and updates only on explicit
`refresh_file_index` calls.
"""
from __future__ import annotations

import os
import platform
import threading
from typing import Iterable

from core.logger import logger


# Subdirectory names that should never be walked. Lowercase-compared.
DEFAULT_EXCLUDES: frozenset[str] = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env",
    "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".tox", "target", "build", "dist", ".gradle",
    ".idea", ".vscode", ".cache", ".local",
})


def _expand_user_roots() -> list[str]:
    """Return the per-user default index roots that actually exist."""
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "Documents"),
        os.path.join(home, "Downloads"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "Pictures"),
        os.path.join(home, "Videos"),
        os.path.join(home, "Music"),
    ]
    return [path for path in candidates if os.path.isdir(path)]


def _external_mount_roots() -> list[str]:
    """Return mounted external drives via psutil if available."""
    try:
        import psutil  # type: ignore  # noqa: PLC0415
    except ImportError:
        return []
    roots: list[str] = []
    try:
        partitions = psutil.disk_partitions(all=False)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("psutil.disk_partitions failed: %s", exc)
        return []
    if platform.system() == "Linux":
        for part in partitions:
            mount = getattr(part, "mountpoint", "") or ""
            if mount.startswith("/mnt/") or mount.startswith("/media/") or mount.startswith("/run/media/"):
                if os.path.isdir(mount):
                    roots.append(mount)
    else:
        for part in partitions:
            mount = getattr(part, "mountpoint", "") or ""
            opts = (getattr(part, "opts", "") or "").lower()
            if mount and os.path.isdir(mount) and ("removable" in opts or "fixed" in opts or platform.system() == "Windows"):
                roots.append(mount)
    return roots


def default_roots() -> list[str]:
    """User dirs + external mounts. Skips paths that don't exist."""
    roots = list(_expand_user_roots())
    for mount in _external_mount_roots():
        if mount not in roots:
            roots.append(mount)
    return roots


class FileIndexer:
    """Background indexer that populates `FileIndexStore`."""

    # Rows flushed to the store per batch during a scan (see scan_once).
    _SCAN_FLUSH_BATCH = 2000

    def __init__(
        self,
        store,
        roots: Iterable[str] | None = None,
        excludes: Iterable[str] | None = None,
        max_files_per_scan: int = 200_000,
    ):
        self.store = store
        self.roots = list(roots) if roots is not None else default_roots()
        self.excludes = frozenset(e.lower() for e in (excludes or DEFAULT_EXCLUDES))
        self.max_files_per_scan = max_files_per_scan
        self._scan_lock = threading.Lock()
        self._watcher = None  # populated by start_watcher() when watchdog is present
        self._stop_event = threading.Event()

    def scan_once(self, roots: Iterable[str] | None = None) -> int:
        """Walk *roots* (or `self.roots`) and upsert every file found.

        Returns the number of files indexed. Honors `max_files_per_scan`
        as a safety cap so a misconfigured root can't exhaust disk.
        """
        targets = list(roots) if roots is not None else self.roots
        if not targets:
            logger.info("[file_indexer] No roots configured; skipping scan.")
            return 0
        with self._scan_lock:
            # Flush to the store in batches as we walk, rather than buffering
            # every row and committing once at the end. Keeps memory bounded
            # for large trees and — because the store commits each batch in its
            # own short transaction — lets interactive turn/audit writes on the
            # shared friday.db interleave instead of stalling behind one giant
            # commit (2026-05-29 latency fix).
            batch: list[dict] = []
            count = 0
            stop = False
            for root in targets:
                if stop:
                    break
                if not os.path.isdir(root):
                    continue
                for row in self._walk(root):
                    if self._stop_event.is_set():
                        stop = True
                        break
                    batch.append(row)
                    count += 1
                    if len(batch) >= self._SCAN_FLUSH_BATCH:
                        self.store.bulk_upsert(batch)
                        batch = []
                    if count >= self.max_files_per_scan:
                        logger.warning(
                            "[file_indexer] Hit max_files_per_scan=%d; stopping early",
                            self.max_files_per_scan,
                        )
                        stop = True
                        break
            if batch:
                self.store.bulk_upsert(batch)
            logger.info("[file_indexer] Indexed %d files across %d root(s)", count, len(targets))
            return count

    def _walk(self, root: str):
        """Iterate (path, name, parent, ext, size, mtime) dicts under *root*."""
        stack = [root]
        while stack:
            current = stack.pop()
            try:
                entries = list(os.scandir(current))
            except (PermissionError, OSError) as exc:
                logger.debug("[file_indexer] skip %s: %s", current, exc)
                continue
            for entry in entries:
                name_lower = entry.name.lower()
                if name_lower.startswith("."):
                    continue
                if name_lower in self.excludes:
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        yield self._entry_to_row(entry)
                except OSError:
                    continue

    @staticmethod
    def _entry_to_row(entry) -> dict:
        try:
            stat = entry.stat(follow_symlinks=False)
        except OSError:
            stat = None
        _, raw_ext = os.path.splitext(entry.name)
        return {
            "path": entry.path,
            "name": entry.name,
            "parent_dir": os.path.dirname(entry.path),
            "ext": raw_ext.lstrip(".").lower(),
            "size": getattr(stat, "st_size", 0),
            "mtime": getattr(stat, "st_mtime", 0.0),
        }

    def start_background_scan(self, initial_delay: float = 0.0) -> threading.Thread:
        """Kick off `scan_once` in a daemon thread; return the thread.

        ``initial_delay`` holds the scan back for a few seconds so the
        filesystem walk doesn't contend with model loading and the first
        few user turns at startup (2026-05-29 startup-latency fix). The
        delay is interruptible via ``stop()``.
        """
        def _run():
            if initial_delay > 0 and self._stop_event.wait(initial_delay):
                return  # stopped during the delay
            self.scan_once()

        thread = threading.Thread(target=_run, name="file-indexer-initial", daemon=True)
        thread.start()
        return thread

    def start_watcher(self) -> bool:
        """Attach a watchdog observer if the package is available.

        Returns True if the watcher started, False otherwise (missing
        watchdog, no roots, etc.). Safe to call repeatedly — only the
        first call attaches an observer.
        """
        if self._watcher is not None:
            return True
        try:
            from watchdog.observers import Observer  # type: ignore  # noqa: PLC0415
            from watchdog.events import FileSystemEventHandler  # type: ignore  # noqa: PLC0415
        except ImportError:
            logger.info("[file_indexer] watchdog not installed; live-update disabled.")
            return False
        if not self.roots:
            return False

        store = self.store

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    store.upsert_file(event.src_path)

            def on_modified(self, event):
                if not event.is_directory:
                    store.upsert_file(event.src_path)

            def on_deleted(self, event):
                if event.is_directory:
                    store.delete_under(event.src_path)
                else:
                    store.delete_path(event.src_path)

            def on_moved(self, event):
                if not event.is_directory:
                    store.delete_path(event.src_path)
                    store.upsert_file(event.dest_path)

        observer = Observer()
        for root in self.roots:
            if os.path.isdir(root):
                observer.schedule(_Handler(), root, recursive=True)
        observer.daemon = True
        observer.start()
        self._watcher = observer
        logger.info("[file_indexer] watchdog observer attached to %d root(s)", len(self.roots))
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._watcher is not None:
            try:
                self._watcher.stop()
                self._watcher.join(timeout=2)
            except Exception:  # pragma: no cover - defensive
                pass
            self._watcher = None

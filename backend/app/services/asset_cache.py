import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any


class AssetHashCache:
    def __init__(self, cache_dir: Path | str | None = None) -> None:
        if cache_dir is not None:
            self._cache_dir = Path(cache_dir)
        else:
            self._cache_dir = Path(
                os.environ.get("ASSET_CACHE_DIR", "/data/derived/asset_cache")
            )
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    @staticmethod
    def compute_bytes_hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def compute_file_hash(self, file_path: Path) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
        return h.hexdigest()

    def _cache_key(self, image_hash: str, prompt: str) -> str:
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        return f"{image_hash}_{prompt_hash}.json"

    def get_cached_result(
        self, image_hash: str, prompt: str
    ) -> dict[str, Any] | None:
        key = self._cache_key(image_hash, prompt)
        cache_file = self._cache_dir / key
        if cache_file.is_file():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def store_result(
        self, image_hash: str, prompt: str, result: dict[str, Any]
    ) -> None:
        key = self._cache_key(image_hash, prompt)
        cache_file = self._cache_dir / key
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self._cache_dir,
                mode="w",
                encoding="utf-8",
                delete=False,
                suffix=".tmp",
            ) as tf:
                tf.write(payload)
                temp_path = Path(tf.name)
            os.replace(temp_path, cache_file)
            temp_path = None
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def cleanup(self, max_age_days: int = 30) -> int:
        """Remove cache files older than max_age_days. Returns the number of files deleted."""
        if not self._cache_dir.exists():
            return 0
        cutoff = time.time() - (max_age_days * 86400)
        removed_count = 0
        for item in self._cache_dir.iterdir():
            if item.is_file():
                try:
                    if item.stat().st_mtime < cutoff:
                        item.unlink()
                        removed_count += 1
                except OSError:
                    pass
        return removed_count

    def get_cache_stats(self) -> dict[str, int]:
        """Return cache statistics including total files count and total size in bytes."""
        if not self._cache_dir.exists():
            return {
                "file_count": 0,
                "files_count": 0,
                "total_files": 0,
                "total_size_bytes": 0,
                "total_size": 0,
            }
        count = 0
        total_size = 0
        for item in self._cache_dir.iterdir():
            if item.is_file():
                count += 1
                try:
                    total_size += item.stat().st_size
                except OSError:
                    pass
        return {
            "file_count": count,
            "files_count": count,
            "total_files": count,
            "total_size_bytes": total_size,
            "total_size": total_size,
        }

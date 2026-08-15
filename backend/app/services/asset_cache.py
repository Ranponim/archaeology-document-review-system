import hashlib
import json
from pathlib import Path
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
        temp_file = cache_file.with_suffix(".tmp")
        temp_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_file.replace(cache_file)

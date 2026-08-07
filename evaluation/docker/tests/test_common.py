from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


DOCKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCKER_ROOT))

from common import hash_tree  # noqa: E402


class HashTreeTests(unittest.TestCase):
    def test_ignores_runtime_cache_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "stable.txt").write_text("stable\n", encoding="utf-8")
            expected = hash_tree(root)
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "module.pyc").write_bytes(b"runtime-specific")
            (root / "candidate.log").write_text("noise\n", encoding="utf-8")
            self.assertEqual(hash_tree(root), expected)


if __name__ == "__main__":
    unittest.main()

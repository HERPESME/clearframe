"""Local JSON persistence for production state (Firestore replaces this in cloud mode)."""

import os
import tempfile
from pathlib import Path

from clearframe.models import ProductionState


class LocalJsonStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, production_id: str) -> Path:
        return self.root / f"{production_id}.json"

    def save(self, state: ProductionState) -> None:
        target = self._path(state.production.id)
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(state.model_dump_json(indent=2))
            os.replace(tmp, target)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def load(self, production_id: str) -> ProductionState:
        return ProductionState.model_validate_json(self._path(production_id).read_text())

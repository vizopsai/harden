"""Stateful pipeline tracking for harden CLI.

Manages .harden/state/ directory to track which stages have been completed,
persist intermediate artifacts (appspec, resource map), and enable resumable
workflows.
"""

import json
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


class Stage(str, Enum):
    """Pipeline stages in order of execution."""

    ANALYZE = "analyze"
    LOCK = "lock"
    PROFILE = "profile"
    GENERATE = "generate"
    TIGHTEN = "tighten"
    TEST = "test"
    AIGENERATE = "aigenerate"


class StateManager:
    """Manages pipeline state in .harden/state/ directory.

    Tracks completed stages, timestamps, and persists intermediate artifacts
    so that later commands can pick up where earlier ones left off.
    """

    def __init__(self, project_path: str):
        self.project_path = os.path.abspath(project_path)
        self.state_dir = os.path.join(self.project_path, ".harden", "state")
        self._pipeline_file = os.path.join(self.state_dir, "pipeline.json")
        self._state: Dict[str, Any] = {}
        self._ensure_dir()
        self._load()

    def _ensure_dir(self):
        """Create state directory if it doesn't exist."""
        Path(self.state_dir).mkdir(parents=True, exist_ok=True)

    def _load(self):
        """Load existing pipeline state from disk."""
        if os.path.exists(self._pipeline_file):
            try:
                with open(self._pipeline_file, "r") as f:
                    self._state = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._state = {}

    def _save(self):
        """Persist pipeline state to disk."""
        try:
            with open(self._pipeline_file, "w") as f:
                json.dump(self._state, f, indent=2)
        except OSError:
            pass

    def record_stage(self, stage: Stage, metadata: Optional[Dict[str, Any]] = None):
        """Record that a stage has been completed.

        Args:
            stage: The pipeline stage that completed.
            metadata: Optional extra data to store (e.g. artifact count, errors).
        """
        stages = self._state.setdefault("stages", {})
        stages[stage.value] = {
            "completed_at": time.time(),
            "completed_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **(metadata or {}),
        }
        self._state["last_stage"] = stage.value
        self._state["updated_at"] = time.time()
        self._save()

    def has_stage(self, stage: Stage) -> bool:
        """Check whether a stage has been completed."""
        return stage.value in self._state.get("stages", {})

    def save_artifact(self, name: str, data: Any):
        """Persist an intermediate artifact as JSON.

        Args:
            name: Artifact name (e.g. "appspec", "resource_map").
            data: JSON-serializable data.
        """
        artifact_path = os.path.join(self.state_dir, f"{name}.json")
        try:
            with open(artifact_path, "w") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def load_artifact(self, name: str) -> Optional[Any]:
        """Load a previously saved artifact.

        Args:
            name: Artifact name (without .json extension).

        Returns:
            Parsed JSON data, or None if not found.
        """
        artifact_path = os.path.join(self.state_dir, f"{name}.json")
        if not os.path.exists(artifact_path):
            return None
        try:
            with open(artifact_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def get_pipeline_summary(self) -> Dict[str, Any]:
        """Return a summary of completed stages and timestamps."""
        return {
            "project_path": self.project_path,
            "stages": self._state.get("stages", {}),
            "last_stage": self._state.get("last_stage"),
            "updated_at": self._state.get("updated_at"),
        }

    def reset(self):
        """Clear all pipeline state."""
        self._state = {}
        self._save()

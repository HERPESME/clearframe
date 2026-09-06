"""The heavy container: analyses, one per request, nothing else."""

from clearframe.worker.app import create_worker_app

__all__ = ["create_worker_app"]

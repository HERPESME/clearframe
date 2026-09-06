"""Storage seams: blobs, the production index, and the analysis job queue.

Each is a protocol with a local implementation and a cloud one, chosen by
`CLEARFRAME_PROFILE`. The local implementations are not stubs — they are what a
laptop and the test suite run, so the behaviour under test is the behaviour that
ships, which is the same discipline the integration clients follow.
"""

from clearframe.storage.blobs import BlobStore, LocalBlobStore, check_key

__all__ = ["BlobStore", "LocalBlobStore", "check_key"]

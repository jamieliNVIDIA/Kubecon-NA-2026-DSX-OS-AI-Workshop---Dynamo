"""Compatibility entrypoint for the shared unlimited log-stream timeout policy."""
from contextlib import contextmanager

from demos.shadow.diagnostics import LogFollowers, unlimited_stream_base


class UnlimitedLogFollowers(LogFollowers):
    def __init__(self, run):
        super().__init__(run)
        self.kbase = unlimited_stream_base(self.kbase)
        # The inherited watch() still appends --request-timeout=8s to its GETs.
        # Only the long-lived `logs --follow` subprocess has an unlimited deadline.


@contextmanager
def continuous_logs(run):
    follower = UnlimitedLogFollowers(run)
    follower.start()
    try:
        yield follower.path
    finally:
        follower.stop()

"""The data package, safe to share across threads.

`arena_kit.data.DataPackage` keeps one SQLite connection (`check_same_thread=False`) for every caller.
In the final every case of a wave prepares at the same moment, and concurrent queries on that one
connection return wrong rows or None fields (measured: about half of 95 concurrent `intel.build`
calls differed from a sequential run). `shared()` wraps the package so every access, including lazy
attributes such as the ID index, holds one lock. The kit itself stays unmodified.
"""

import threading


class SharedPackage:
    """Every method call and attribute read of the wrapped package runs under one re-entrant lock."""

    def __init__(self, pkg):
        object.__setattr__(self, "_pkg", pkg)
        object.__setattr__(self, "_lock", threading.RLock())

    def __getattr__(self, name):
        with self._lock:  # a cached_property (the ID index) may query SQLite on first read
            attr = getattr(self._pkg, name)
        if not callable(attr):
            return attr

        def locked(*args, **kwargs):
            with self._lock:
                return attr(*args, **kwargs)

        return locked


def shared(pkg):
    """`pkg` wrapped for concurrent use; None and already-wrapped packages pass through."""
    return pkg if pkg is None or isinstance(pkg, SharedPackage) else SharedPackage(pkg)

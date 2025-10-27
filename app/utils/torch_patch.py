"""Torch compatibility patches.

PyTorch 2.6 changed the default behavior of torch.load regarding the
`weights_only` parameter (now enabling stricter security by default).
Older code or third-party libraries (including some versions of ultralytics)
may not specify this flag and can raise errors like:

    RuntimeError: weight only load failed, in PyTorch 2.6 we changed the default value of the 'weights_only' ...

This helper provides a safe monkeypatch that wraps torch.load and ensures
`weights_only=False` when not explicitly passed, restoring legacy behavior.

Usage:
    from app.utils.torch_patch import ensure_torch_load_legacy
    ensure_torch_load_legacy()

The patch is idempotent and will not wrap multiple times.
"""
from __future__ import annotations

from typing import Any

_PATCHED = False

def ensure_torch_load_legacy(force: bool = False) -> None:
    """Monkeypatch torch.load to supply weights_only=False when omitted.

    Args:
        force: If True, reapply even if previously patched (rarely needed).
    """
    global _PATCHED
    if _PATCHED and not force:
        return
    try:
        import torch  # type: ignore
    except Exception:
        return

    orig_load = getattr(torch, "load", None)
    if not callable(orig_load):  # pragma: no cover
        return

    def _wrapped_load(*args: Any, **kwargs: Any):
        # Only inject if caller didn't set weights_only explicitly.
        if "weights_only" not in kwargs:
            kwargs["weights_only"] = False
        try:
            return orig_load(*args, **kwargs)
        except Exception as e:
            # If error mentions weights_only guidance, retry once with False explicitly.
            msg = str(e).lower()
            if "weights_only" in msg and not kwargs.get("weights_only", False):
                kwargs["weights_only"] = False
                return orig_load(*args, **kwargs)
            raise

    # Avoid double wrapping.
    if getattr(orig_load, "__name__", "") != "_wrapped_load":
        try:
            torch.load = _wrapped_load  # type: ignore
            _PATCHED = True
        except Exception:
            pass

def is_patched() -> bool:
    return _PATCHED

__all__ = ["ensure_torch_load_legacy", "is_patched"]

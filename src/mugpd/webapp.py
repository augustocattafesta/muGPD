"""Backward-compatible entrypoint for the muGPD Flask web UI.

The implementation now lives in the `mugpd.web` package.
"""

from .web.app import create_app, main

__all__ = ["create_app", "main"]


if __name__ == "__main__":
    main()

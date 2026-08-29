"""FastAPI layer exposing Nexa to the web frontend.

Note: we deliberately do NOT re-export the `app` instance here. Doing so would
shadow the `nexa.api.app` submodule. Import it explicitly where needed:

    from nexa.api.app import app, create_app
"""

from nexa.api.app import create_app

__all__ = ["create_app"]

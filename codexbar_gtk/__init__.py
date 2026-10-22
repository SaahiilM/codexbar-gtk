"""CodexBar for Linux — a native GTK4/libadwaita front-end for the CodexBar CLI."""

from .version import BUILD as __build__
from .version import SHORT_VERSION as __version__
from .version import display_string

APP_ID = "com.steipete.CodexBarGTK"

__all__ = ["APP_ID", "__build__", "__version__", "display_string"]

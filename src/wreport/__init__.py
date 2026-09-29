"""weekly-report -- turn daily reports into archived weekly reports.

The package is import-safe and side-effect free: nothing touches the filesystem at
import time, so tests can drive the parser and generators directly.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
"""pyocd-pack-inject - inject local CMSIS-Pack files into the pyOCD
global pack cache so pyOCD discovers them without --pack.

Project: https://github.com/USTHzhanglu/pyocd-pack-inject
"""

from .manager import (PackManager, PackManagerError, cpm_available,
                      default_data_path)
from .version import (HELP_URL, __appname__, __author__, __copyright__,
                      __version__)

__all__ = [
    "PackManager",
    "PackManagerError",
    "cpm_available",
    "default_data_path",
    "HELP_URL",
    "__appname__",
    "__version__",
    "__author__",
    "__copyright__",
]

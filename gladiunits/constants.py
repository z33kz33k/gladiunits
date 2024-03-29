"""

    gladiunits.constants.py
    ~~~~~~~~~~~~~~~~~~~~~~~
    Script's constants

    @author: z33k

"""
import logging
from collections import namedtuple
from pathlib import Path
from typing import Any, Callable, Dict, Tuple, TypeVar

_log = logging.getLogger(__name__)

# type hints
T = TypeVar("T")
Json = Dict[str, Any]
PathLike = str | Path
Method = Callable[[Any, Tuple[Any, ...]], Any]  # method with signature def methodname(self, *args)
Function = Callable[[Tuple[Any, ...]], Any]  # function with signature def funcname(*args)

FILENAME_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
READABLE_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
SECONDS_IN_YEAR = 365.25 * 24 * 60 * 60  # with leap years

OUTPUT_DIR = Path("temp") / "output"
if not OUTPUT_DIR.is_dir():
    _log.warning(f"Creating missing output directory at: '{OUTPUT_DIR.resolve()}'")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

XML_DIR = Path("xml")



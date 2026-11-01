"""rptsort - reorder, rename and scan-skip repeater channels in CHIRP CSV files."""

__version__ = "0.2.0"


class RptsortError(Exception):
    """A problem the user can fix (bad input, bad config, missing data)."""

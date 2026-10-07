"""Suite-wide test setup.

Qt must run offscreen (no display under pytest) and the platform choice has
to be in place before any test module imports PyQt, so it lives here rather
than at the top of individual test files.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

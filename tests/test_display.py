from __future__ import annotations

import unittest
from unittest.mock import patch

from easyfi.display import configure_windows_dpi_awareness


class DisplayConfigurationTests(unittest.TestCase):
    def test_dpi_setup_is_a_noop_outside_windows(self) -> None:
        with patch("easyfi.display.sys.platform", "linux"):
            self.assertEqual(configure_windows_dpi_awareness(), "not-windows")


if __name__ == "__main__":
    unittest.main()

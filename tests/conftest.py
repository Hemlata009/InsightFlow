"""Tests always use the SHIPPED rule book: missing-value choices saved from the web page
(configs/choices/<ID>.yaml) must not change test results or the frozen baseline."""

import os

os.environ["INSIGHTFLOW_IGNORE_CHOICES"] = "1"

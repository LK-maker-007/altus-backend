#!/usr/bin/env python
from __future__ import annotations

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError("Couldn't import Django. Is your virtualenv active?") from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

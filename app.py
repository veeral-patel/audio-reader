from __future__ import annotations

import logging

from ui import render_app


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)


if __name__ == "__main__":
    render_app()

from __future__ import annotations

from .connection import get_engine
from .schema import run_migrations


def main() -> None:
    engine = get_engine()
    run_migrations(engine)


if __name__ == "__main__":
    main()

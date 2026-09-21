import logging

from .config import load_settings
from .scanner import VolumeScanner


def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    VolumeScanner(settings).run()


if __name__ == "__main__":
    main()


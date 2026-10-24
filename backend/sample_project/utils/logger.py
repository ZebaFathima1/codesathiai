"""Tiny logging helper used across ShopEasy."""
import logging
import os


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for ``name``."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    return logger

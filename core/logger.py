import logging
import sys

class CustomFormatter(logging.Formatter):
    """
    Compact event-based formatter with color coding.
    Format: [HH:MM:SS] [LEVEL] message
    """
    grey = "\x1b[38;20m"
    blue = "\x1b[34;20m"
    green = "\x1b[32;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    
    # Compact format: [HH:MM:SS] [LEVEL] message
    format_str = "[%(asctime)s] [%(levelname)-8s] %(message)s"

    FORMATS = {
        logging.DEBUG: grey + format_str + reset,
        logging.INFO: green + format_str + reset,
        logging.WARNING: yellow + format_str + reset,
        logging.ERROR: red + format_str + reset,
        logging.CRITICAL: bold_red + format_str + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt="%H:%M:%S")
        return formatter.format(record)

def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Get a configured logger instance with one-time handler setup.
    """
    logger = logging.getLogger(name)
    
    # Only configure if not already set up
    if not logger.handlers:
        logger.setLevel(level)
        channel = logging.StreamHandler(sys.stdout)
        channel.setFormatter(CustomFormatter())
        logger.addHandler(channel)
        logger.propagate = False
    
    return logger

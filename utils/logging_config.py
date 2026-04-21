import logging
import sys
from datetime import datetime


def setup_logging() -> logging.Logger:
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    root_logger.handlers.clear()
    
    # Use stdout stream but ensure handler encodes in utf-8 to avoid UnicodeEncodeError on Windows consoles
    console_handler = logging.StreamHandler(sys.stdout)
    try:
        # Python 3.7+ supports setting encoding on the handler
        console_handler.setStream(sys.stdout)
        # If the underlying stream supports 'buffer' with 'raw' encoding, this will generally work.
        console_handler.encoding = 'utf-8'
    except Exception:
        # If we cannot set encoding, rely on the formatter and set the handler to replace errors
        console_handler.addFilter(lambda record: record)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    try:
        file_handler = logging.FileHandler('voice_agent.log')
        # Ensure file handler writes UTF-8
        try:
            file_handler = logging.FileHandler('voice_agent.log', encoding='utf-8')
        except TypeError:
            # older Python versions may not accept encoding kwarg
            file_handler = logging.FileHandler('voice_agent.log')
        file_handler.setLevel(logging.ERROR)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Could not create log file: {e}")
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

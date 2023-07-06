import dotenv
import gzip
import logging
import os
import shutil
from pathlib import Path


def setup_logger():
    dotenv.load_dotenv()
    # https://docs.python.org/3/howto/logging.html#configuring-logging
    fmt = '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s'
    # https://docs.python.org/3/library/time.html#time.strftime
    datefmt = '%Y-%m-%d %I:%M:%S %z'
    logging.basicConfig(level=logging.INFO, format=fmt, datefmt=datefmt)
    logger = logging.getLogger('vrc')
    logger.setLevel(logging.INFO)

    logfile = os.environ['VRC_LOG_PATH']

    def _rotator(source: str, dest: str):
        """Compresses the log file at each rotation"""
        with open(source, 'rb') as log_source, gzip.open(dest, 'wb') as log_out:
            shutil.copyfileobj(log_source, log_out)
        os.remove(source)

    p_logfile = Path(logfile)
    p_logfile.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(p_logfile, maxBytes=2**20, backupCount=100)
    handler.rotator = _rotator
    handler.namer = lambda name: name + '.gz'
    logger.addHandler(handler)
    return logger
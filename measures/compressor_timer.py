import logging

from api.Sumitomo.f70_rest import F70Rest
import time

from utils.logger import configure_logger

configure_logger()
logger = logging.getLogger(__name__)

seconds = 60 * 60 * 1
logger.info(f"Waiting {seconds} s before start")
time.sleep(seconds)
logger.info(f"Starting compressor")

compressor = F70Rest(host="192.168.129.106", port=21024)

compressor.turn_on()

logger.info(f"Compressor started")

# time.sleep(5)

# compressor.turn_off()

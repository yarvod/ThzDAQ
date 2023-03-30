import logging

from interactors.block import Block


logger = logging.getLogger(__name__)


def update_block(block_ip, block_port):
    block = Block(block_ip, block_port)
    block.host = block_ip
    block.port = int(block_port)
    result = block.get_bias_data()
    logger.info(f"Health check bias {result}")

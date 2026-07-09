import logging
import os

logger = logging.getLogger('MainGun')
logger.setLevel(logging.DEBUG if os.path.isfile('.debug_mods') else logging.ERROR)

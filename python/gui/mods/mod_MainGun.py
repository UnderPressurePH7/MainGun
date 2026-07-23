from MainGun.utils import logger
from MainGun import initialize, finalize

__version__ = '0.0.5'
__author__ = 'Under_Pressure'
__mod_name__ = 'MainGun'


def init():
    logger.debug('START LOADING: v%s', __version__)
    try:
        initialize()
        logger.info('LOADED SUCCESSFULLY: v%s', __version__)
    except Exception as e:
        logger.error('LOADING FAILED: %s', e)
        import traceback
        logger.error('Traceback: %s', traceback.format_exc())


def fini():
    logger.debug('SHUTTING DOWN: v%s', __version__)
    try:
        finalize()
        logger.info('SHUTDOWN COMPLETE: v%s', __version__)
    except Exception as e:
        logger.error('SHUTDOWN FAILED: %s', e)
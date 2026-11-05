__version__ = '0.0.10'
__author__ = 'Under_Pressure'
__mod_name__ = 'MainGun'


def init():
    try:
        from MainGun.utils import logger
    except Exception:
        logger = None
    try:
        from MainGun import initialize
        if logger is not None:
            logger.debug('START LOADING: v%s', __version__)
        initialize()
        if logger is not None:
            logger.info('LOADED SUCCESSFULLY: v%s', __version__)
    except Exception as e:
        import traceback
        if logger is not None:
            logger.error('LOADING FAILED: %s', e)
            logger.error('Traceback: %s', traceback.format_exc())
        else:
            import logging
            logging.getLogger('MainGun').exception('LOADING FAILED: %s', e)


def fini():
    try:
        try:
            from MainGun.utils import logger
        except Exception:
            logger = None
        from MainGun import finalize
        if logger is not None:
            logger.debug('SHUTTING DOWN: v%s', __version__)
        finalize()
        if logger is not None:
            logger.info('SHUTDOWN COMPLETE: v%s', __version__)
    except Exception as e:
        import logging
        logging.getLogger('MainGun').exception('SHUTDOWN FAILED: %s', e)

from .utils import logger
from .battle_state_events import g_battleStateEvents
from .views import MainGunPanel, registerGamefaceComponents, unregisterGamefaceComponents
from . import damage_tracker

__all__ = ('initialize', 'finalize')

g_mainGunPanel = None


def initialize():
    global g_mainGunPanel
    try:
        registerGamefaceComponents()
        if g_mainGunPanel is None:
            g_mainGunPanel = MainGunPanel()
        damage_tracker.initialize(g_mainGunPanel)
        logger.debug('[MainGun] initialized')
    except Exception as e:
        logger.error('[MainGun] initialization failed: %s', e)
        import traceback
        logger.error('[MainGun] Traceback: %s', traceback.format_exc())
        finalize()


def finalize():
    global g_mainGunPanel
    try:
        damage_tracker.finalize()
        if g_mainGunPanel is not None:
            g_mainGunPanel.destroy()
            g_mainGunPanel = None
        unregisterGamefaceComponents()
        g_battleStateEvents.fini()
    except Exception as e:
        logger.error('[MainGun] finalization failed: %s', e)

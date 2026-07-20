import logging
import os

import BigWorld

try:
    import GUI
except Exception:
    GUI = None

logger = logging.getLogger('MainGun')
logger.setLevel(logging.DEBUG if os.path.isfile('.debug_mods') else logging.ERROR)

BASE_SCREEN = (1920, 1080)


def cancelCallbackSafe(cbid):
    try:
        if cbid is not None:
            BigWorld.cancelCallback(cbid)
    except Exception:
        pass


def screenResolution():
    try:
        if GUI is not None:
            width, height = GUI.screenResolution()[:2]
            if width > 0 and height > 0:
                return (int(width), int(height))
    except Exception:
        pass
    try:
        width, height = BigWorld.screenWidth(), BigWorld.screenHeight()
        if width > 0 and height > 0:
            return (int(width), int(height))
    except Exception:
        pass
    return BASE_SCREEN


def cursorPixels(cursor):
    normX, normY = cursor.position
    screenWidth, screenHeight = screenResolution()
    return (int((normX + 1.0) * 0.5 * screenWidth), int((1.0 - normY) * 0.5 * screenHeight))

import json
import os

import BigWorld

from ..utils import logger

try:
    _prefsFilePath = BigWorld.wg_getPreferencesFilePath()
except AttributeError:
    _prefsFilePath = BigWorld.getPreferencesFilePath()

_CACHE_DIR = os.path.normpath(os.path.join(os.path.dirname(_prefsFilePath), 'mods', 'maingun'))
_POS_FILE = os.path.join(_CACHE_DIR, 'pos.dat')

_POS_VERSION = 1

DEFAULT_CONFIG = {'panelOffset': [300, 30], 'displayMode': 1}


class ConfigFile(object):

    def __init__(self):
        self.panelOffset = list(DEFAULT_CONFIG['panelOffset'])
        self.displayMode = DEFAULT_CONFIG['displayMode']
        self._loaded = False

    def path(self):
        return _POS_FILE

    def load(self):
        if self._loaded:
            return True
        self._loaded = True
        try:
            if not os.path.isfile(_POS_FILE):
                return True
            with open(_POS_FILE, 'rb') as fh:
                raw = fh.read()
            if not raw:
                return True
            data = json.loads(raw)
            if not isinstance(data, dict) or int(data.get('version', 0)) != _POS_VERSION:
                return True
            offset = data.get('panelOffset', DEFAULT_CONFIG['panelOffset'])
            self.panelOffset = [int(offset[0]), int(offset[1])]
            displayMode = int(data.get('displayMode', DEFAULT_CONFIG['displayMode']))
            self.displayMode = displayMode if displayMode in (1, 2) else DEFAULT_CONFIG['displayMode']
            return True
        except Exception as e:
            logger.error('[ConfigFile] load failed: %s', e)
            self.panelOffset = list(DEFAULT_CONFIG['panelOffset'])
            self.displayMode = DEFAULT_CONFIG['displayMode']
            return False

    def save(self):
        try:
            if not os.path.isdir(_CACHE_DIR):
                os.makedirs(_CACHE_DIR)
            data = {
                'version': _POS_VERSION,
                'panelOffset': [int(self.panelOffset[0]), int(self.panelOffset[1])],
                'displayMode': int(self.displayMode)
            }
            with open(_POS_FILE, 'wb') as fh:
                fh.write(json.dumps(data))
            return True
        except Exception as e:
            logger.error('[ConfigFile] save failed: %s', e)
            return False


g_configFile = ConfigFile()
g_configFile.load()

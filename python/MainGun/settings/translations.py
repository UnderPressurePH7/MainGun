import json

import ResMgr
from helpers import getClientLanguage

from ..utils import logger


class TranslationManager(object):

    def __init__(self):
        self.fallbackLanguage = 'en'
        self.translationPathTemplate = 'mods/under_pressure.MainGun/{}.json'
        self._defaultTranslationsMap = {}
        self._translationsMap = {}
        self._currentLanguage = None
        self._loaded = False

    def _safeJsonLoad(self, content, language):
        try:
            if isinstance(content, bytes):
                content = content.decode('utf-8')
            return json.loads(content)
        except Exception as e:
            logger.error('[TranslationManager] JSON parse failed for %s: %s', language, e)
            return None

    def _loadLanguageFile(self, language):
        try:
            section = ResMgr.openSection(self.translationPathTemplate.format(language))
            if section is None:
                return None
            content = section.asBinary
            if not content:
                return None
            data = self._safeJsonLoad(content, language)
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.error('[TranslationManager] load failed for %s: %s', language, e)
            return None

    def _defaults(self):
        return {
            'modname': 'Main Gun',
            'mainGun': 'Main Gun'
        }

    def load(self, force=False):
        if self._loaded and not force:
            return True
        defaultData = self._loadLanguageFile(self.fallbackLanguage) or self._defaults()
        self._defaultTranslationsMap = defaultData
        try:
            language = getClientLanguage()
        except Exception:
            language = self.fallbackLanguage
        self._currentLanguage = language
        if language != self.fallbackLanguage:
            data = self._loadLanguageFile(language)
            self._translationsMap = data if data is not None else defaultData.copy()
        else:
            self._translationsMap = defaultData.copy()
        self._loaded = True
        return True

    def get(self, key):
        if not self._loaded:
            self.load()
        if key in self._translationsMap:
            return self._translationsMap[key]
        if key in self._defaultTranslationsMap:
            return self._defaultTranslationsMap[key]
        return key


g_translationManager = TranslationManager()
g_translationManager.load()


def getTranslation(key):
    return g_translationManager.get(key)

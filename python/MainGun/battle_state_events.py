import Event
from gui.shared import g_eventBus, EVENT_BUS_SCOPE
from gui.shared.events import GameEvent
from gui.shared.personality import ServicesLocator

from .utils import logger


class BattleStateEvents(object):

    @property
    def visible(self):
        return not any((self._hiddenByInterface, self._hiddenByStatsPopup, self._hiddenByKillCam))

    @property
    def interfaceScale(self):
        return self._interfaceScale

    @property
    def extendedInfo(self):
        return self._extendedInfo

    def __init__(self):
        self._hiddenByInterface = False
        self._hiddenByStatsPopup = False
        self._hiddenByKillCam = False
        self._interfaceScale = 1.0
        self._extendedInfo = False
        self._killCamCtrl = None
        self.onBattleClosed = Event.SafeEvent()
        self.onGUIVisibility = Event.SafeEvent()
        self.onScaleChanged = Event.SafeEvent()
        self.onExtendedInfo = Event.SafeEvent()
        self._subscribeAppLoader()
        self._subscribeEventBus()

    def fini(self):
        try:
            ServicesLocator.appLoader.onGUISpaceEntered -= self._onGUISpaceEntered
            ServicesLocator.appLoader.onGUISpaceLeft -= self._onGUISpaceLeft
        except Exception:
            pass
        try:
            ServicesLocator.settingsCore.interfaceScale.onScaleChanged -= self._onScaleFactorChanged
        except Exception:
            pass
        for eventType, handler in self._eventBusListeners():
            try:
                g_eventBus.removeListener(eventType, handler, scope=EVENT_BUS_SCOPE.BATTLE)
            except Exception:
                pass
        self._unsubscribeKillCam()
        self.onBattleClosed.clear()
        self.onGUIVisibility.clear()
        self.onScaleChanged.clear()
        self.onExtendedInfo.clear()

    def _subscribeAppLoader(self):
        try:
            ServicesLocator.appLoader.onGUISpaceEntered += self._onGUISpaceEntered
            ServicesLocator.appLoader.onGUISpaceLeft += self._onGUISpaceLeft
        except Exception as e:
            logger.error('[BattleStateEvents] appLoader subscribe failed: %s', e)
        try:
            ServicesLocator.settingsCore.interfaceScale.onScaleChanged += self._onScaleFactorChanged
        except Exception as e:
            logger.debug('[BattleStateEvents] scale subscribe failed: %s', e)

    def _subscribeEventBus(self):
        for eventType, handler in self._eventBusListeners():
            try:
                g_eventBus.addListener(eventType, handler, scope=EVENT_BUS_SCOPE.BATTLE)
            except Exception as e:
                logger.error('[BattleStateEvents] event bus subscribe failed: %s', e)

    def _eventBusListeners(self):
        listeners = [(GameEvent.GUI_VISIBILITY, self._onGUIVisibility)]
        for eventName in ('FULL_STATS', 'FULL_STATS_QUEST_PROGRESS', 'FULL_STATS_PERSONAL_RESERVES', 'EVENT_STATS'):
            eventType = getattr(GameEvent, eventName, None)
            if eventType is not None:
                listeners.append((eventType, self._onToggleFullStats))
        eventType = getattr(GameEvent, 'SHOW_EXTENDED_INFO', None)
        if eventType is not None:
            listeners.append((eventType, self._onExtendedInfo))
        return listeners

    def _onGUISpaceEntered(self, spaceID):
        from skeletons.gui.app_loader import GuiGlobalSpaceID
        if spaceID == GuiGlobalSpaceID.BATTLE:
            self._hiddenByInterface = False
            self._hiddenByStatsPopup = False
            self._hiddenByKillCam = False
            self._extendedInfo = False
            self._handleBattleLoad()

    def _onGUISpaceLeft(self, spaceID):
        from skeletons.gui.app_loader import GuiGlobalSpaceID
        if spaceID == GuiGlobalSpaceID.BATTLE:
            self._unsubscribeKillCam()
            self.onBattleClosed()

    def _onGUIVisibility(self, event):
        hidden = not event.ctx.get('visible', True)
        if hidden != self._hiddenByInterface:
            self._hiddenByInterface = hidden
            self.onGUIVisibility(self.visible)

    def _onToggleFullStats(self, event):
        hidden = event.ctx.get('isDown', False)
        if hidden != self._hiddenByStatsPopup:
            self._hiddenByStatsPopup = hidden
            self.onGUIVisibility(self.visible)

    def _onScaleFactorChanged(self, scale):
        if self._interfaceScale != scale:
            self._interfaceScale = scale
            self.onScaleChanged(scale)

    def _onExtendedInfo(self, event):
        isDown = bool(event.ctx.get('isDown', False))
        if isDown != self._extendedInfo:
            self._extendedInfo = isDown
            self.onExtendedInfo(isDown)

    def _handleBattleLoad(self):
        try:
            from helpers import dependency
            from skeletons.account_helpers.settings_core import ISettingsCore
            from skeletons.gui.battle_session import IBattleSessionProvider
            settingsCore = dependency.instance(ISettingsCore)
            scale = float(settingsCore.interfaceScale.get())
            if self._interfaceScale != scale:
                self._interfaceScale = scale
                self.onScaleChanged(scale)
            self._unsubscribeKillCam()
            sessionProvider = dependency.instance(IBattleSessionProvider)
            killCamCtrl = getattr(sessionProvider.shared, 'killCamCtrl', None)
            if killCamCtrl:
                self._killCamCtrl = killCamCtrl
                killCamCtrl.onKillCamModeStateChanged += self._onKillCamStateChanged
        except Exception as e:
            logger.debug('[BattleStateEvents] battle load fallback: %s', e)

    def _unsubscribeKillCam(self):
        if not self._killCamCtrl:
            return
        try:
            self._killCamCtrl.onKillCamModeStateChanged -= self._onKillCamStateChanged
        except Exception:
            pass
        self._killCamCtrl = None

    def _onKillCamStateChanged(self, state, *args, **kwargs):
        try:
            from gui.shared.events import DeathCamEvent
            values = DeathCamEvent.State
            hidden = (values.STARTING.value <= state.value) and (state.value < values.FINISHED.value)
            if self._hiddenByKillCam != hidden:
                self._hiddenByKillCam = hidden
                self.onGUIVisibility(self.visible)
        except Exception:
            pass


g_battleStateEvents = BattleStateEvents()

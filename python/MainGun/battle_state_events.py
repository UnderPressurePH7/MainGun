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

    def __init__(self):
        self._hiddenByInterface = False
        self._hiddenByStatsPopup = False
        self._hiddenByKillCam = False
        self._interfaceScale = 1.0
        self._killCamCtrl = None
        self.onBattleLoaded = Event.SafeEvent()
        self.onBattleClosed = Event.SafeEvent()
        self.onGUIVisibility = Event.SafeEvent()
        self.onScaleChanged = Event.SafeEvent()
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
        try:
            g_eventBus.removeListener(GameEvent.GUI_VISIBILITY, self._onGUIVisibility, scope=EVENT_BUS_SCOPE.BATTLE)
        except Exception:
            pass
        for eventName in ('FULL_STATS', 'FULL_STATS_QUEST_PROGRESS', 'FULL_STATS_PERSONAL_RESERVES', 'EVENT_STATS'):
            try:
                eventType = getattr(GameEvent, eventName, None)
                if eventType is not None:
                    g_eventBus.removeListener(eventType, self._onToggleFullStats, scope=EVENT_BUS_SCOPE.BATTLE)
            except Exception:
                pass
        self._unsubscribeKillCam()
        self.onBattleLoaded.clear()
        self.onBattleClosed.clear()
        self.onGUIVisibility.clear()
        self.onScaleChanged.clear()

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
        try:
            g_eventBus.addListener(GameEvent.GUI_VISIBILITY, self._onGUIVisibility, scope=EVENT_BUS_SCOPE.BATTLE)
        except Exception as e:
            logger.error('[BattleStateEvents] GUI visibility subscribe failed: %s', e)
        for eventName in ('FULL_STATS', 'FULL_STATS_QUEST_PROGRESS', 'FULL_STATS_PERSONAL_RESERVES', 'EVENT_STATS'):
            try:
                eventType = getattr(GameEvent, eventName, None)
                if eventType is not None:
                    g_eventBus.addListener(eventType, self._onToggleFullStats, scope=EVENT_BUS_SCOPE.BATTLE)
            except Exception:
                pass

    def _onGUISpaceEntered(self, spaceID):
        from skeletons.gui.app_loader import GuiGlobalSpaceID
        if spaceID == GuiGlobalSpaceID.BATTLE:
            self._hiddenByInterface = False
            self._hiddenByStatsPopup = False
            self._hiddenByKillCam = False
            self._handleBattleLoad()
            self.onBattleLoaded()

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

    def _handleBattleLoad(self):
        try:
            from helpers import dependency
            from skeletons.account_helpers.settings_core import ISettingsCore
            from skeletons.gui.battle_session import IBattleSessionProvider
            settingsCore = dependency.instance(ISettingsCore)
            self._interfaceScale = round(settingsCore.interfaceScale.get(), 1)
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

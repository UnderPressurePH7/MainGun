import json

import BigWorld
import Keys
from gui import InputHandler

try:
    import GUI
except Exception:
    GUI = None

try:
    from gui import g_guiResetters
except Exception:
    g_guiResetters = None

from ..battle_state_events import g_battleStateEvents
from ..settings import g_configFile, getTranslation
from ..utils import logger

try:
    from openwg_gameface import ModDynAccessor, manager as gamefaceResMap, on_ready as gamefaceOnReady
    from frameworks.wulf import ViewFlags, ViewModel, ViewSettings, WindowFlags, WindowLayer, WindowStatus
    from gui.impl.gui_decorators import args2params
    from gui.impl.pub import ViewImpl, WindowImpl
    from helpers import dependency
    from skeletons.gui.impl import IGuiLoader
    _GF_OK = True
except Exception:
    ModDynAccessor = gamefaceResMap = gamefaceOnReady = None
    ViewFlags = ViewModel = ViewSettings = WindowFlags = WindowLayer = WindowStatus = None
    ViewImpl = WindowImpl = args2params = None
    dependency = IGuiLoader = None
    _GF_OK = False

LAYOUT_KEY = 'mods/under_pressure/MainGunBattle/layoutID'
VIEW_NAME = 'MainGunBattle'
BASE_SCREEN = (1920, 1080)
BOUNDARY_GAP = 0
DRAG_THRESHOLD = 20


def registerGamefaceComponents():
    logger.debug('[MainGunPanel] Gameface components use dynamic res_map registration')


def unregisterGamefaceComponents():
    logger.debug('[MainGunPanel] Gameface res_map unregistration')


def _cancelCallbackSafe(cbid):
    try:
        if cbid is not None:
            BigWorld.cancelCallback(cbid)
    except Exception:
        pass


def _screenResolution():
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


def _cursorPixels(cursor):
    normX, normY = cursor.position
    screenWidth, screenHeight = _screenResolution()
    return (int((normX + 1.0) * 0.5 * screenWidth), int((1.0 - normY) * 0.5 * screenHeight))


if _GF_OK:
    _GF_LAYOUT = ModDynAccessor(LAYOUT_KEY)

    class _MainGunPanelModel(ViewModel):

        def __init__(self, payload):
            self._payload = payload
            super(_MainGunPanelModel, self).__init__(properties=1, commands=3)

        def _initialize(self):
            super(_MainGunPanelModel, self)._initialize()
            self._addStringProperty('payload', self._payload)
            self.onReady = self._addCommand('onReady')
            self.onDebug = self._addCommand('onDebug')
            self.onCmd = self._addCommand('onCmd')

        def setPayload(self, value):
            self._setString(0, value)

    class _MainGunPanelViewImpl(ViewImpl):

        def __init__(self, owner):
            self._owner = owner
            model = _MainGunPanelModel(owner.buildPayload())
            owner._setModel(model, publish=False)
            settings = ViewSettings(layoutID=_GF_LAYOUT(), flags=ViewFlags.VIEW, model=model)
            super(_MainGunPanelViewImpl, self).__init__(settings)

        def _getEvents(self):
            model = self.getViewModel()
            return (
                (model.onReady, self._owner._onReady),
                (model.onDebug, self._onDebug),
                (model.onCmd, self._onCmd),
            )

        @args2params(str)
        def _onDebug(self, message):
            logger.debug('[MainGunPanel] JS: %s', message)

        @args2params(str, str)
        def _onCmd(self, name, value):
            self._owner._handleCommand(name, value)

        def _finalize(self):
            self._owner._setModel(None)
            super(_MainGunPanelViewImpl, self)._finalize()
            self._owner._onViewFinalized()

    class _MainGunPanelWindow(WindowImpl):

        def __init__(self, content, parent):
            super(_MainGunPanelWindow, self).__init__(WindowFlags.WINDOW, content=content, layer=getattr(WindowLayer, 'WINDOW', WindowLayer.OVERLAY), name=VIEW_NAME, parent=parent)


class MainGunPanel(object):

    def __init__(self):
        self._window = None
        self._model = None
        self._nativeReady = False
        self._token = 0
        self._destroyed = False
        self._isInitialized = False
        self._isVisible = False
        self._extendedInfo = False
        self._displayMode = g_configFile.displayMode
        self._state = self._defaultState()
        self._offset = list(g_configFile.panelOffset)
        self._lastSavedOffset = tuple(self._offset)
        self._position = [0, 0]
        self._positionChanged = False
        self._scaleFactor = 1.0
        self._size = (180, 26)
        self._viewSizeReported = False
        self._guiResetterBound = False
        self._resizeCallbackID = None
        self._dragCallbackID = None
        self._dragging = False
        self._mouseWasDown = False
        self._dragStartCursor = None
        self._dragStartPosition = None

    @staticmethod
    def _defaultState():
        return {
            'current': 0,
            'need': 0,
            'remaining': 0,
            'completed': False,
            'teamDamageLeader': False,
            'mainGunObtained': False,
            'playerDead': False
        }

    def onBattleStart(self):
        if self._isInitialized:
            return
        self._destroyed = False
        self._nativeReady = False
        self._calculateScaleFactor()
        self._syncPositionFromOffset()
        self._isVisible = g_battleStateEvents.visible
        self._extendedInfo = g_battleStateEvents.extendedInfo
        g_battleStateEvents.onGUIVisibility += self._onGUIVisibilityChanged
        g_battleStateEvents.onScaleChanged += self._onInterfaceScaleChanged
        g_battleStateEvents.onExtendedInfo += self._onExtendedInfoChanged
        g_battleStateEvents.onBattleClosed += self._onBattleClosed
        self._isInitialized = True
        self._ensureWindow()
        self._startDragTicker()
        self._bindGuiResetter()
        logger.debug('[MainGunPanel] Battle started')

    def _onBattleClosed(self):
        self.onBattleEnd()

    def onBattleEnd(self):
        if not self._isInitialized:
            return
        self._isInitialized = False
        try:
            g_battleStateEvents.onGUIVisibility -= self._onGUIVisibilityChanged
            g_battleStateEvents.onScaleChanged -= self._onInterfaceScaleChanged
            g_battleStateEvents.onExtendedInfo -= self._onExtendedInfoChanged
            g_battleStateEvents.onBattleClosed -= self._onBattleClosed
        except Exception:
            pass
        self._stopDragTicker()
        self._unbindGuiResetter()
        self._savePositionIfChanged()
        self._dropWindow()
        self._state = self._defaultState()
        self._isVisible = False
        self._extendedInfo = False
        logger.debug('[MainGunPanel] Battle ended')

    def updateState(self, state):
        if state:
            self._state.update(state)
            if self._isInitialized:
                self.publish()

    def destroy(self):
        self.onBattleEnd()
        self._destroyed = True

    def buildPayload(self):
        return json.dumps({
            'visible': bool(self._isVisible),
            'extendedInfo': bool(self._extendedInfo),
            'displayMode': int(self._displayMode),
            'scale': self._scaleFactor,
            'size': {'w': self._size[0], 'h': self._size[1]},
            'state': self._state,
            'l10n': {'mainGun': getTranslation('mainGun')}
        }, ensure_ascii=False)

    def _setModel(self, model, publish=True):
        self._model = model
        if publish:
            self.publish()

    def publish(self):
        if self._model is None:
            return
        payload = self.buildPayload()
        try:
            with self._model.transaction() as model:
                model.setPayload(payload)
        except Exception:
            pass
        self._move()

    def _onReady(self, *args):
        self._nativeReady = True
        self.publish()
        self._move()

    def _onViewFinalized(self):
        self._window = None
        self._model = None
        self._nativeReady = False
        self._token += 1
        if self._isInitialized and not self._destroyed:
            BigWorld.callback(0.1, self._ensureWindow)

    def _ensureWindow(self):
        if self._destroyed or self._window is not None:
            return
        if not _GF_OK or gamefaceResMap is None:
            logger.error('[MainGunPanel] openwg_gameface is required for Gameface panel')
            return
        self._token += 1
        token = self._token
        if gamefaceResMap.isResMapValidated:
            self._loadWindow(token)
        else:
            gamefaceOnReady(lambda: self._loadWindow(token))

    def _loadWindow(self, token, retry=0):
        if token != self._token or self._destroyed or not self._isInitialized:
            return
        try:
            parent = dependency.instance(IGuiLoader).windowsManager.getMainWindow()
        except Exception:
            parent = None
        if parent is None or parent.proxy is None or parent.windowStatus != WindowStatus.LOADED:
            if retry < 100:
                BigWorld.callback(0.1, lambda: self._loadWindow(token, retry + 1))
            return
        try:
            self._window = _MainGunPanelWindow(_MainGunPanelViewImpl(self), parent)
            self._window.load()
        except Exception:
            logger.exception('[MainGunPanel] Failed to load Gameface window')
            self._window = None

    def _dropWindow(self):
        self._token += 1
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None
        self._model = None
        self._nativeReady = False

    def _move(self):
        if self._window is None or not self._nativeReady:
            return
        self._clampPosition()
        scaleX, scaleY = self._windowScale()
        try:
            self._window.move(int(round(self._position[0] / scaleX)), int(round(self._position[1] / scaleY)))
        except Exception:
            pass

    def _windowScale(self):
        if self._window is None:
            return (1.0, 1.0)
        try:
            nativeW, nativeH = self._window.size[:2]
            nativeW = float(nativeW)
            nativeH = float(nativeH)
        except Exception:
            return (1.0, 1.0)
        viewW, viewH = self._size
        if nativeW <= 10 or nativeH <= 10 or viewW <= 10 or viewH <= 10:
            return (1.0, 1.0)
        scaleW = float(viewW) / nativeW
        scaleH = float(viewH) / nativeH
        if abs(scaleW - scaleH) > 0.1 or not 0.4 <= scaleW <= 4.0:
            return (1.0, 1.0)
        return (scaleW, scaleH)

    def _anchor(self):
        screenWidth, _ = _screenResolution()
        yPos = int(round(70.0 * max(0.5, min(2.5, float(self._scaleFactor or 1.0)))))
        return (int(screenWidth * 0.5 - self._size[0] * 0.5), yPos)

    def _syncPositionFromOffset(self):
        anchorX, anchorY = self._anchor()
        self._position[0] = int(anchorX + self._offset[0])
        self._position[1] = int(anchorY + self._offset[1])
        self._clampPosition()

    def _syncOffsetFromPosition(self):
        anchorX, anchorY = self._anchor()
        self._offset = [int(self._position[0] - anchorX), int(self._position[1] - anchorY)]

    def _clampPosition(self):
        screenWidth, screenHeight = _screenResolution()
        width, height = self._size
        maxX = max(BOUNDARY_GAP, screenWidth - width - BOUNDARY_GAP)
        maxY = max(BOUNDARY_GAP, screenHeight - height - BOUNDARY_GAP)
        self._position[0] = max(BOUNDARY_GAP, min(int(self._position[0]), maxX))
        self._position[1] = max(BOUNDARY_GAP, min(int(self._position[1]), maxY))

    def _setPosition(self, xPos, yPos):
        oldPosition = tuple(self._position)
        self._position[0] = int(round(xPos))
        self._position[1] = int(round(yPos))
        self._clampPosition()
        if tuple(self._position) != oldPosition:
            self._positionChanged = True
            self._move()

    def _handleCommand(self, name, value):
        if name == 'onModeChanged':
            try:
                displayMode = int(value)
            except Exception:
                return
            if displayMode not in (1, 2) or displayMode == self._displayMode:
                return
            self._displayMode = displayMode
            g_configFile.displayMode = displayMode
            g_configFile.save()
            self.publish()
            logger.debug('[MainGunPanel] Display mode changed: %s', displayMode)
        elif name == 'onSize':
            try:
                parts = str(value).split('x')
                width = max(1, int(float(parts[0])))
                height = max(1, int(float(parts[1])))
            except Exception:
                return
            self._viewSizeReported = True
            if (width, height) != tuple(self._size):
                self._size = (width, height)
                self._syncPositionFromOffset()
                self._move()

    def _bindGuiResetter(self):
        if self._guiResetterBound or g_guiResetters is None:
            return
        try:
            g_guiResetters.add(self._onScreenResize)
            self._guiResetterBound = True
        except Exception:
            pass

    def _unbindGuiResetter(self):
        if not self._guiResetterBound:
            return
        try:
            g_guiResetters.discard(self._onScreenResize)
        except Exception:
            pass
        self._guiResetterBound = False
        _cancelCallbackSafe(self._resizeCallbackID)
        self._resizeCallbackID = None

    def _onScreenResize(self, *args):
        if self._destroyed or self._window is None:
            return
        self._syncPositionFromOffset()
        self._move()
        _cancelCallbackSafe(self._resizeCallbackID)
        self._resizeCallbackID = BigWorld.callback(0.2, self._resizeResync)

    def _resizeResync(self):
        self._resizeCallbackID = None
        if self._destroyed or self._window is None:
            return
        self._syncPositionFromOffset()
        self._move()

    def _startDragTicker(self):
        if self._dragCallbackID is None:
            self._dragCallbackID = BigWorld.callback(0.0, self._updateDragState)

    def _stopDragTicker(self):
        _cancelCallbackSafe(self._dragCallbackID)
        self._dragCallbackID = None
        self._dragging = False
        self._mouseWasDown = False
        self._dragStartCursor = None
        self._dragStartPosition = None

    def _updateDragState(self):
        self._dragCallbackID = None
        if self._isInitialized and self._window is not None:
            self._handleMouseDrag()
            self._dragCallbackID = BigWorld.callback(0.0, self._updateDragState)

    def _handleMouseDrag(self):
        if GUI is None:
            return
        cursor = GUI.mcursor()
        mouseDown = BigWorld.isKeyDown(Keys.KEY_LEFTMOUSE)
        if not cursor.visible or not cursor.inWindow or not cursor.inFocus:
            if self._dragging:
                self._finishDrag()
            self._dragging = False
            self._mouseWasDown = False
            return
        cursorPos = _cursorPixels(cursor)
        if mouseDown and not self._mouseWasDown and self._isCursorOver(cursorPos):
            self._dragging = True
            self._dragStartCursor = cursorPos
            self._dragStartPosition = tuple(self._position)
        elif not mouseDown:
            if self._dragging:
                self._finishDrag()
            self._dragging = False
        if self._dragging and self._dragStartCursor is not None and self._dragStartPosition is not None:
            dx = cursorPos[0] - self._dragStartCursor[0]
            dy = cursorPos[1] - self._dragStartCursor[1]
            if dx * dx + dy * dy >= DRAG_THRESHOLD * DRAG_THRESHOLD:
                self._setPosition(self._dragStartPosition[0] + dx, self._dragStartPosition[1] + dy)
        self._mouseWasDown = mouseDown

    def _finishDrag(self):
        self._dragging = False
        self._syncOffsetFromPosition()
        self._savePositionIfChanged()

    def _isCursorOver(self, cursorPos):
        if not self._isVisible:
            return False
        left, top = self._position[0], self._position[1]
        width, height = self._size
        return left <= cursorPos[0] <= left + width and top <= cursorPos[1] <= top + height

    def _onGUIVisibilityChanged(self, isVisible):
        if self._isInitialized:
            self._isVisible = bool(isVisible)
            self.publish()

    def _onInterfaceScaleChanged(self, scale):
        if self._isInitialized:
            self._calculateScaleFactor()
            self._syncPositionFromOffset()
            self.publish()

    def _onExtendedInfoChanged(self, isDown):
        if self._isInitialized:
            self._extendedInfo = bool(isDown)
            self.publish()

    def _calculateScaleFactor(self):
        try:
            self._scaleFactor = g_battleStateEvents.interfaceScale if g_battleStateEvents.interfaceScale > 0 else 1.0
        except Exception:
            self._scaleFactor = 1.0

    def _savePositionIfChanged(self):
        if not self._positionChanged:
            return
        self._syncOffsetFromPosition()
        current = tuple(self._offset)
        if current != self._lastSavedOffset:
            g_configFile.panelOffset = list(self._offset)
            g_configFile.save()
            self._lastSavedOffset = current
            logger.debug('[MainGunPanel] Position saved: offset=(%s, %s)', self._offset[0], self._offset[1])
        self._positionChanged = False

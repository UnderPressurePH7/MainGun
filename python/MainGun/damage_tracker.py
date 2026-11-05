import math
import weakref

import BigWorld
import constants
from PlayerEvents import g_playerEvents
from gui.battle_control.battle_constants import FEEDBACK_EVENT_ID

try:
    from gui.battle_control.battle_constants import PERSONAL_EFFICIENCY_TYPE
except ImportError:
    PERSONAL_EFFICIENCY_TYPE = None

from .utils import logger, cancelCallbackSafe


MIN_GUN_DAMAGE = 1000
DAMAGE_RATE = 0.2
ATTACH_RETRY_DELAY = 0.5
ATTACH_MAX_ATTEMPTS = 20


def _scheduleWeak(owner, delay, methodName, session):
    ref = weakref.ref(owner)

    def _fire():
        target = ref()
        if target is None or target._session != session:
            return
        getattr(target, methodName)()

    return BigWorld.callback(delay, _fire)


class DamageTracker(object):

    def __init__(self, panel):
        self._panel = panel
        self._started = False
        self._totalEnemiesHP = 0
        self._enemiesHP = 0
        self._baseNeed = 0
        self._need = 0
        self._current = 0
        self._feedbackDamage = 0
        self._efficiencyDamage = 0
        self._playerVehicleID = None
        self._playerTeam = None
        self._healthMap = {}
        self._damageByVehicle = {}
        self._feedbackCtrl = None
        self._feedbackHooked = False
        self._efficiencyCtrl = None
        self._efficiencyHooked = False
        self._startCallbackID = None
        self._attachCallbackID = None
        self._publishCallbackID = None
        self._attachAttempts = 0
        self._attachGaveUp = False
        self._stateDirty = False
        self._session = 0
        self._playerDead = False
        self._arena = None
        self._healthHooked = False
        self._killHooked = False
        self._vehicleListHooked = False
        self._vehicleListEvents = []
        self._topAllyDamageValue = 0
        self._lastPublished = None
        self._resetState()

    def _resetState(self):
        self._started = False
        self._totalEnemiesHP = 0
        self._enemiesHP = 0
        self._baseNeed = 0
        self._need = 0
        self._current = 0
        self._feedbackDamage = 0
        self._efficiencyDamage = 0
        self._playerVehicleID = None
        self._playerTeam = None
        self._healthMap = {}
        self._damageByVehicle = {}
        self._topAllyDamageValue = 0
        self._playerDead = False
        self._lastPublished = None
        self._attachAttempts = 0
        self._attachGaveUp = False
        self._stateDirty = False

    def start(self):
        if self._started or self._startCallbackID is not None:
            return
        self._tryStartBattle(0)

    def stop(self):
        self._session += 1
        self._cancelCallbacks()
        self._detachFeedback()
        self._detachEfficiency()
        self._detachArenaEvents()
        if self._started:
            self._panel.onBattleEnd()
        self._resetState()

    def destroy(self):
        self.stop()

    def _cancelCallbacks(self):
        cancelCallbackSafe(self._startCallbackID)
        cancelCallbackSafe(self._attachCallbackID)
        cancelCallbackSafe(self._publishCallbackID)
        self._startCallbackID = None
        self._attachCallbackID = None
        self._publishCallbackID = None

    def _tryStartBattle(self, attempt):
        cancelCallbackSafe(self._startCallbackID)
        self._startCallbackID = None
        allowed = self._isAllowedBattle()
        if allowed is False:
            logger.debug('[MainGun] battle skipped: only random battles are supported')
            return
        if allowed is True and self._startBattleImpl():
            return
        if attempt < 19:
            self._startCallbackID = BigWorld.callback(0.5, lambda: self._tryStartBattle(attempt + 1))
        else:
            logger.warning('[MainGun] battle start failed after 20 attempts (arena/player context unavailable)')

    def _startBattleImpl(self):
        self._session += 1
        cancelCallbackSafe(self._publishCallbackID)
        cancelCallbackSafe(self._attachCallbackID)
        self._publishCallbackID = None
        self._attachCallbackID = None
        self._resetState()
        self._captureContext()
        if self._playerVehicleID is None or self._playerTeam is None:
            return False
        totalEnemiesHP = self._calcTotalEnemiesHP()
        if totalEnemiesHP <= 0:
            return False
        self._totalEnemiesHP = totalEnemiesHP
        self._baseNeed = self._computeNeed(totalEnemiesHP)
        self._need = self._baseNeed
        self._initHealthMap()
        self._started = True
        self._panel.onBattleStart()
        missing = self._ensureSubscriptions()
        if missing:
            self._scheduleAttachRetry()
        self._publishState()
        logger.info(
            '[MainGun] battle started: enemyHP=%d need=%d',
            self._totalEnemiesHP,
            self._need
        )
        return True

    def _ensureSubscriptions(self):
        if not self._feedbackHooked:
            self._attachFeedback()
        if not self._efficiencyHooked:
            self._attachEfficiency()
        if not (self._healthHooked and self._killHooked and self._vehicleListHooked):
            self._attachArenaEvents()
        missing = []
        if not self._feedbackHooked:
            missing.append('feedback')
        if not self._efficiencyHooked and PERSONAL_EFFICIENCY_TYPE is not None:
            missing.append('personalEfficiencyCtrl')
        if not self._healthHooked:
            missing.append('arena.onVehicleHealthChanged')
        if not self._killHooked:
            missing.append('arena.onVehicleKilled')
        if not self._vehicleListHooked:
            missing.append('arena vehicle list events')
        return missing

    def _scheduleAttachRetry(self):
        if self._attachCallbackID is not None or self._attachGaveUp:
            return
        if not self._started:
            return
        self._attachCallbackID = _scheduleWeak(
            self, ATTACH_RETRY_DELAY, '_onAttachRetry', self._session)

    def _onAttachRetry(self):
        self._attachCallbackID = None
        if not self._started:
            return
        missing = self._ensureSubscriptions()
        if not missing:
            self._attachAttempts = 0
            logger.debug('[MainGun] all event sources attached')
            return
        self._attachAttempts += 1
        if self._attachAttempts >= ATTACH_MAX_ATTEMPTS:
            self._attachGaveUp = True
            logger.error(
                '[MainGun] event sources still unavailable after %d attempts: %s',
                self._attachAttempts,
                ', '.join(missing)
            )
            return
        self._scheduleAttachRetry()

    def _isAllowedBattle(self):
        try:
            player = BigWorld.player()
            arena = getattr(player, 'arena', None)
            if arena is None:
                return None
            guiType = getattr(arena, 'guiType', None)
            if guiType is None:
                return None
            randomGuiType = getattr(constants.ARENA_GUI_TYPE, 'RANDOM', None)
            if randomGuiType is None:
                return False
            return guiType == randomGuiType
        except Exception:
            return None

    def _captureContext(self):
        try:
            player = BigWorld.player()
            self._playerVehicleID = getattr(player, 'playerVehicleID', None)
            if self._playerVehicleID is None and hasattr(player, 'getVehicleAttached'):
                vehicle = player.getVehicleAttached()
                self._playerVehicleID = getattr(vehicle, 'id', None)
            self._playerTeam = getattr(player, 'team', None)
        except Exception:
            self._playerVehicleID = None
            self._playerTeam = None

    def _vehicleItems(self):
        vehicles = self._arenaVehicles()
        try:
            return vehicles.iteritems() if hasattr(vehicles, 'iteritems') else vehicles.items()
        except Exception:
            return []

    def _arenaVehicles(self):
        try:
            arena = getattr(BigWorld.player(), 'arena', None)
            return getattr(arena, 'vehicles', {}) if arena is not None else {}
        except Exception:
            return {}

    def _vehicleDataGet(self, data, key, default=None):
        try:
            if hasattr(data, 'get'):
                return data.get(key, default)
            return getattr(data, key, default)
        except Exception:
            return default

    def _teamForVehicle(self, vehicleID):
        try:
            vehicles = self._arenaVehicles()
            vehicleID = int(vehicleID)
            data = vehicles.get(vehicleID) if hasattr(vehicles, 'get') else None
            return self._vehicleDataGet(data, 'team', None)
        except Exception:
            return None

    def _isEnemyVehicle(self, vehicleID):
        team = self._teamForVehicle(vehicleID)
        return team is not None and self._playerTeam is not None and team != self._playerTeam

    def _isAllyVehicle(self, vehicleID):
        team = self._teamForVehicle(vehicleID)
        return team is not None and self._playerTeam is not None and team == self._playerTeam

    def _readHealthField(self, data, keys):
        for key in keys:
            value = self._vehicleDataGet(data, key, None)
            if value is None:
                continue
            try:
                return max(0, int(value))
            except Exception:
                continue
        return None

    def _maxHealthOf(self, data):
        hp = self._readHealthField(data, ('maxHealth', 'maxHp'))
        if hp is None:
            hp = self._readHealthField(data, ('health',))
        return 0 if hp is None else hp

    def _currentHealthOf(self, data, vehicleID=None):
        hp = self._readHealthField(data, ('health',))
        if hp is None:
            hp = self._liveEntityHealth(vehicleID)
        if hp is None:
            hp = self._maxHealthOf(data)
        return hp

    def _liveEntityHealth(self, vehicleID):
        try:
            entity = BigWorld.entities.get(int(vehicleID)) if vehicleID is not None else None
            alive = getattr(entity, 'isAlive', None) if entity is not None else None
            if callable(alive):
                alive = alive()
            if entity is not None and alive is not False:
                value = getattr(entity, 'health', None)
                if value is not None:
                    return max(0, int(value))
        except Exception:
            pass
        return None

    def _maxHealthForVehicle(self, vehicleID):
        try:
            vehicles = self._arenaVehicles()
            data = vehicles.get(int(vehicleID)) if hasattr(vehicles, 'get') else None
            if data is None:
                return 0
            return self._maxHealthOf(data)
        except Exception:
            return 0

    def _calcTotalEnemiesHP(self):
        total = 0
        for vehicleID, data in self._vehicleItems():
            try:
                team = self._vehicleDataGet(data, 'team', None)
                if team is None or self._playerTeam is None or team == self._playerTeam:
                    continue
                total += self._maxHealthOf(data)
            except Exception:
                continue
        return total

    def _computeNeed(self, totalEnemiesHP):
        return max(
            MIN_GUN_DAMAGE,
            int(math.ceil(float(totalEnemiesHP) * DAMAGE_RATE))
        )

    def _initHealthMap(self):
        self._syncHealthMap(True)

    def _syncMissingHealthEntries(self):
        self._syncHealthMap(False)

    def _syncHealthMap(self, reset):
        if reset:
            self._healthMap = {}
            self._enemiesHP = 0
        for vehicleID, data in self._vehicleItems():
            try:
                vehicleID = int(vehicleID)
                liveHP = self._liveEntityHealth(vehicleID)
                oldHP = self._healthMap.get(vehicleID)
                if oldHP is not None and liveHP is None:
                    continue
                hp = liveHP if liveHP is not None else self._currentHealthOf(data, vehicleID)
                self._healthMap[vehicleID] = hp
                if self._isEnemyVehicle(vehicleID):
                    self._enemiesHP += hp if oldHP is None else hp - oldHP
            except Exception:
                continue

    def _sameVehicle(self, firstID, secondID):
        try:
            return int(firstID) == int(secondID)
        except Exception:
            return firstID == secondID

    def _topAllyDamage(self):
        return self._topAllyDamageValue

    def _updateGunScore(self):
        self._need = max(self._baseNeed, self._topAllyDamage())

    def _recordPlayerDamage(self, damage):
        try:
            damage = int(damage or 0)
        except Exception:
            damage = 0
        if damage <= 0 or not self._started:
            return
        self._feedbackDamage += damage
        self._syncCurrentDamage()

    def _syncCurrentDamage(self):
        current = max(self._feedbackDamage, self._efficiencyDamage)
        if current != self._current:
            self._current = current
            self._invalidate()

    def _recordAllyDamage(self, attackerID, damage):
        try:
            damage = int(damage or 0)
        except Exception:
            damage = 0
        if damage <= 0 or attackerID is None:
            return
        if self._sameVehicle(attackerID, self._playerVehicleID):
            return
        if not self._isAllyVehicle(attackerID):
            return
        totalDamage = int(self._damageByVehicle.get(attackerID, 0)) + damage
        self._damageByVehicle[attackerID] = totalDamage
        self._topAllyDamageValue = max(self._topAllyDamageValue, totalDamage)
        if totalDamage > self._need:
            self._need = totalDamage

    def _updateEnemyHealth(self, targetID, damage):
        if not self._isEnemyVehicle(targetID):
            return 0
        try:
            targetID = int(targetID)
            damage = max(0, int(damage or 0))
        except Exception:
            return 0
        oldHP = self._healthMap.get(targetID, None)
        if oldHP is None:
            oldHP = self._maxHealthForVehicle(targetID)
        oldHP = max(0, int(oldHP or 0))
        newHP = max(0, oldHP - damage)
        self._healthMap[targetID] = newHP
        self._enemiesHP = max(0, self._enemiesHP - (oldHP - newHP))
        return oldHP - newHP

    def _isHealthShortage(self):
        damageLeft = int(self._need) - int(self._current)
        return damageLeft > 0 and int(self._enemiesHP) < damageLeft

    def _isFailed(self):
        return bool(self._playerDead) or self._isHealthShortage()

    def _onVehicleHealthChanged(self, targetID, attackerID, damage):
        if not self._started:
            return
        try:
            damage = int(damage or 0)
            if damage <= 0:
                return
            appliedDamage = self._updateEnemyHealth(targetID, damage)
            if appliedDamage > 0:
                # Health events only cover vehicles currently in view; ally damage outside view is not observable here.
                self._recordAllyDamage(attackerID, appliedDamage)
                self._invalidate()
        except Exception as e:
            logger.error('[MainGun] vehicle health event failed: %s', e)

    def _damageFromObj(self, obj):
        if obj is None:
            return 0
        for name in ('damage', 'damageDealt', 'health', 'hp', 'value'):
            try:
                value = obj.get(name) if hasattr(obj, 'get') else getattr(obj, name)
                if value:
                    return int(value)
            except Exception:
                pass
        for name in ('getDamage', 'getHealth', 'getValue'):
            try:
                getter = getattr(obj, name, None)
                if getter is not None:
                    value = getter()
                    if value:
                        return int(value)
            except Exception:
                pass
        if isinstance(obj, (tuple, list)):
            for item in obj:
                value = self._damageFromObj(item)
                if value:
                    return value
        return 0

    def _damageFromFeedbackOne(self, event):
        try:
            if not hasattr(event, 'getType'):
                return 0
            if event.getType() != FEEDBACK_EVENT_ID.PLAYER_DAMAGED_HP_ENEMY:
                return 0
            return max(0, self._damageFromObj(event.getExtra()))
        except Exception:
            return 0

    def _onPlayerFeedbackReceived(self, events):
        if not self._started:
            return
        try:
            if isinstance(events, (list, tuple)):
                packet = events
            else:
                packet = (events,)
            damage = 0
            for event in packet:
                damage += self._damageFromFeedbackOne(event)
            self._recordPlayerDamage(damage)
        except Exception as e:
            logger.error('[MainGun] feedback failed: %s', e)

    def _attachFeedback(self):
        try:
            return self._attachTrackerEvent(
                '_feedbackCtrl', '_feedbackHooked', 'feedback',
                'onPlayerFeedbackReceived', self._onPlayerFeedbackReceived)
        except Exception as e:
            logger.error('[MainGun] feedback attach failed: %s', e)
            return False

    def _detachFeedback(self):
        self._detachTrackerEvent('_feedbackCtrl', '_feedbackHooked', 'onPlayerFeedbackReceived', self._onPlayerFeedbackReceived)

    def _attachEfficiency(self):
        if PERSONAL_EFFICIENCY_TYPE is None:
            return False
        try:
            if not self._attachTrackerEvent(
                    '_efficiencyCtrl', '_efficiencyHooked', 'personalEfficiencyCtrl',
                    'onTotalEfficiencyUpdated', self._onTotalEfficiencyUpdated,
                    'getTotalEfficiency'):
                return False
            self._onTotalEfficiencyUpdated()
            return True
        except Exception as e:
            logger.error('[MainGun] efficiency attach failed: %s', e)
            return False

    def _detachEfficiency(self):
        self._detachTrackerEvent('_efficiencyCtrl', '_efficiencyHooked', 'onTotalEfficiencyUpdated', self._onTotalEfficiencyUpdated)

    def _sharedGuiSessionProvider(self):
        player = BigWorld.player()
        provider = getattr(player, 'guiSessionProvider', None)
        return getattr(provider, 'shared', None) if provider is not None else None

    def _attachTrackerEvent(self, ctrlAttr, hookedAttr, sharedName, eventName, handler, requiredMethod=None):
        shared = self._sharedGuiSessionProvider()
        ctrl = getattr(shared, sharedName, None) if shared is not None else None
        if ctrl is None or (requiredMethod and not hasattr(ctrl, requiredMethod)):
            return False
        if getattr(self, ctrlAttr) is ctrl and getattr(self, hookedAttr):
            return True
        self._detachTrackerEvent(ctrlAttr, hookedAttr, eventName, handler)
        event = getattr(ctrl, eventName, None)
        if event is None:
            return False
        event += handler
        setattr(self, ctrlAttr, ctrl)
        setattr(self, hookedAttr, True)
        return True

    def _detachTrackerEvent(self, ctrlAttr, hookedAttr, eventName, handler):
        ctrl = getattr(self, ctrlAttr)
        if ctrl is not None and getattr(self, hookedAttr):
            try:
                event = getattr(ctrl, eventName, None)
                if event is not None:
                    event -= handler
            except Exception:
                pass
        setattr(self, ctrlAttr, None)
        setattr(self, hookedAttr, False)

    def _onTotalEfficiencyUpdated(self, *args, **kwargs):
        if not self._started or self._efficiencyCtrl is None:
            return
        try:
            total = int(self._efficiencyCtrl.getTotalEfficiency(PERSONAL_EFFICIENCY_TYPE.DAMAGE) or 0)
        except Exception as e:
            logger.error('[MainGun] efficiency read failed: %s', e)
            return
        self._efficiencyDamage = max(0, total)
        self._syncCurrentDamage()

    def _attachArenaEvents(self):
        try:
            arena = getattr(BigWorld.player(), 'arena', None)
            if arena is None:
                return False
            if self._arena is not None and self._arena is not arena:
                self._detachArenaEvents()
            self._arena = arena
            if not self._healthHooked:
                healthEvent = getattr(arena, 'onVehicleHealthChanged', None)
                if healthEvent is not None:
                    healthEvent += self._onVehicleHealthChanged
                    self._healthHooked = True
            if not self._killHooked:
                killEvent = getattr(arena, 'onVehicleKilled', None)
                if killEvent is not None:
                    killEvent += self._onVehicleKilled
                    self._killHooked = True
            if not self._vehicleListHooked:
                self._subscribeVehicleListEvents(arena)
            return self._healthHooked and self._killHooked and self._vehicleListHooked
        except Exception as e:
            logger.error('[MainGun] arena events attach failed: %s', e)
            return False

    def _detachArenaEvents(self):
        if self._arena is not None:
            if self._healthHooked:
                try:
                    event = getattr(self._arena, 'onVehicleHealthChanged', None)
                    if event is not None:
                        event -= self._onVehicleHealthChanged
                except Exception:
                    pass
            if self._killHooked:
                try:
                    event = getattr(self._arena, 'onVehicleKilled', None)
                    if event is not None:
                        event -= self._onVehicleKilled
                except Exception:
                    pass
            for eventName, handler in self._vehicleListEvents:
                try:
                    event = getattr(self._arena, eventName, None)
                    if event is not None:
                        event -= handler
                except Exception:
                    pass
        self._arena = None
        self._healthHooked = False
        self._killHooked = False
        self._vehicleListHooked = False
        self._vehicleListEvents = []

    def _subscribeVehicleListEvents(self, arena):
        events = (('onNewVehicleListReceived', self._onVehicleListChanged),
                  ('onVehicleAdded', self._onVehicleAdded),
                  ('onVehicleUpdated', self._onVehicleAdded))
        for eventName, handler in events:
            if (eventName, handler) in self._vehicleListEvents:
                continue
            event = getattr(arena, eventName, None)
            if event is not None:
                try:
                    event += handler
                    self._vehicleListEvents.append((eventName, handler))
                except Exception as e:
                    logger.error('[MainGun] arena %s attach failed: %s', eventName, e)
        self._vehicleListHooked = len(self._vehicleListEvents) == len(events)

    def _onVehicleListChanged(self, *args):
        if not self._started:
            return
        self._syncMissingHealthEntries()
        totalEnemiesHP = self._calcTotalEnemiesHP()
        if totalEnemiesHP > self._totalEnemiesHP:
            self._totalEnemiesHP = totalEnemiesHP
            self._baseNeed = self._computeNeed(totalEnemiesHP)
            self._updateGunScore()
            self._invalidate()

    def _onVehicleAdded(self, vehicleID=None, *args):
        self._onVehicleListChanged()

    def _onVehicleKilled(self, targetID, *args, **kwargs):
        try:
            if not self._started:
                return
            changed = False
            if self._playerVehicleID is not None and self._sameVehicle(targetID, self._playerVehicleID):
                if not self._playerDead:
                    self._playerDead = True
                    changed = True
                    logger.info('[MainGun] player vehicle killed')
            elif self._isEnemyVehicle(targetID):
                targetKey = int(targetID)
                oldHP = max(0, int(self._healthMap.get(targetKey, 0)))
                if oldHP > 0:
                    self._healthMap[targetKey] = 0
                    self._enemiesHP = max(0, self._enemiesHP - oldHP)
                    changed = True
            if changed:
                self._invalidate()
        except Exception as e:
            logger.error('[MainGun] kill event failed: %s', e)

    def _isTeamDamageLeader(self):
        return self._current >= self._topAllyDamage()

    def _invalidate(self):
        if not self._started:
            return
        self._stateDirty = True
        if self._publishCallbackID is None:
            self._publishCallbackID = _scheduleWeak(
                self, 0.0, '_flushState', self._session)

    def _flushState(self):
        self._publishCallbackID = None
        if not self._started or not self._stateDirty:
            return
        self._stateDirty = False
        self._publishState()

    def _publishState(self):
        self._stateDirty = False
        remaining = max(0, int(self._need) - int(self._current))
        current = int(self._current)
        need = int(self._need)
        completed = need > 0 and current >= need
        # TODO: confirm whether equal damage with an ally counts as completion.
        leader = self._isTeamDamageLeader()
        obtained = bool(completed and leader)
        failed = self._isFailed()
        snapshot = (
            current,
            need,
            bool(completed),
            bool(leader),
            bool(obtained),
            bool(self._playerDead),
            bool(failed)
        )
        if snapshot == self._lastPublished:
            return
        self._lastPublished = snapshot
        self._panel.updateState({
            'remaining': int(remaining),
            'mainGunObtained': bool(obtained),
            'playerDead': bool(self._playerDead),
            'failed': bool(failed)
        })


g_tracker = None
_playerEventsBound = False


def _onAvatarReady(*args, **kwargs):
    try:
        if g_tracker is not None:
            g_tracker.start()
    except Exception as e:
        logger.error('[MainGun] start failed: %s', e)


def _onAvatarBecomeNonPlayer(*args, **kwargs):
    try:
        if g_tracker is not None:
            g_tracker.stop()
    except Exception:
        pass


def initialize(panel):
    global g_tracker
    global _playerEventsBound
    if g_tracker is None:
        g_tracker = DamageTracker(panel)
    if _playerEventsBound:
        return
    g_playerEvents.onAvatarReady += _onAvatarReady
    g_playerEvents.onAvatarBecomeNonPlayer += _onAvatarBecomeNonPlayer
    g_playerEvents.onAccountShowGUI += _onAvatarBecomeNonPlayer
    g_playerEvents.onAccountBecomeNonPlayer += _onAvatarBecomeNonPlayer
    g_playerEvents.onDisconnected += _onAvatarBecomeNonPlayer
    _playerEventsBound = True
    logger.info('[MainGun] tracker initialized (player events)')


def finalize():
    global g_tracker
    global _playerEventsBound
    if _playerEventsBound:
        try:
            g_playerEvents.onAvatarReady -= _onAvatarReady
            g_playerEvents.onAvatarBecomeNonPlayer -= _onAvatarBecomeNonPlayer
            g_playerEvents.onAccountShowGUI -= _onAvatarBecomeNonPlayer
            g_playerEvents.onAccountBecomeNonPlayer -= _onAvatarBecomeNonPlayer
            g_playerEvents.onDisconnected -= _onAvatarBecomeNonPlayer
        except Exception:
            pass
        _playerEventsBound = False
    try:
        if g_tracker is not None:
            g_tracker.destroy()
    except Exception:
        pass
    g_tracker = None

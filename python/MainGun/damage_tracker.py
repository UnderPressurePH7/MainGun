import math

import BigWorld
import constants
from PlayerEvents import g_playerEvents
from gui.battle_control.battle_constants import FEEDBACK_EVENT_ID

from .utils import logger, cancelCallbackSafe


MIN_GUN_DAMAGE = 1000
DAMAGE_RATE = 0.2


class DamageTracker(object):

    def __init__(self, panel):
        self._panel = panel
        self._started = False
        self._totalEnemiesHP = 0
        self._enemiesHP = 0
        self._baseNeed = 0
        self._need = 0
        self._current = 0
        self._playerVehicleID = None
        self._playerTeam = None
        self._healthMap = {}
        self._damageByVehicle = {}
        self._feedbackCtrl = None
        self._feedbackHooked = False
        self._startCallbackID = None
        self._recalcCallbackID = None
        self._playerDead = False
        self._warning = False
        self._arena = None
        self._healthHooked = False
        self._killHooked = False
        self._lastPublished = None

    def start(self):
        if self._started:
            return
        self._tryStartBattle(0)

    def stop(self):
        self._cancelCallbacks()
        self._detachFeedback()
        self._detachArenaEvents()
        if self._started:
            self._panel.onBattleEnd()
        self._started = False
        self._totalEnemiesHP = 0
        self._enemiesHP = 0
        self._baseNeed = 0
        self._need = 0
        self._current = 0
        self._playerVehicleID = None
        self._playerTeam = None
        self._healthMap = {}
        self._damageByVehicle = {}
        self._playerDead = False
        self._warning = False
        self._lastPublished = None

    def destroy(self):
        self.stop()

    def _cancelCallbacks(self):
        cancelCallbackSafe(self._startCallbackID)
        cancelCallbackSafe(self._recalcCallbackID)
        self._startCallbackID = None
        self._recalcCallbackID = None

    def _tryStartBattle(self, attempt):
        self._startCallbackID = None
        allowed = self._isAllowedBattle()
        if allowed is False:
            logger.debug('[MainGun] battle skipped: only random battles are supported')
            return
        if allowed is True and self._startBattleImpl():
            return
        if attempt < 20:
            self._startCallbackID = BigWorld.callback(0.5, lambda: self._tryStartBattle(attempt + 1))

    def _startBattleImpl(self):
        if self._isAllowedBattle() is not True:
            return False
        self._captureContext()
        if self._playerVehicleID is None or self._playerTeam is None:
            return False
        totalEnemiesHP = self._calcTotalEnemiesHP()
        if totalEnemiesHP <= 0:
            return False
        self._totalEnemiesHP = totalEnemiesHP
        self._baseNeed = self._computeNeed(totalEnemiesHP)
        self._need = self._baseNeed
        self._current = 0
        self._damageByVehicle = {}
        self._playerDead = False
        self._warning = False
        self._lastPublished = None
        self._initHealthMap()
        self._started = True
        self._panel.onBattleStart()
        self._attachFeedback()
        self._attachArenaEvents()
        self._publishState()
        self._scheduleRecalc()
        logger.info(
            '[MainGun] battle started: enemyHP=%d need=%d',
            self._totalEnemiesHP,
            self._need
        )
        return True

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
        try:
            arena = getattr(BigWorld.player(), 'arena', None)
            vehicles = getattr(arena, 'vehicles', {}) if arena is not None else {}
            return vehicles.iteritems() if hasattr(vehicles, 'iteritems') else vehicles.items()
        except Exception:
            return []

    def _vehicleDataGet(self, data, key, default=None):
        try:
            if hasattr(data, 'get'):
                return data.get(key, default)
            return getattr(data, key, default)
        except Exception:
            return default

    def _teamForVehicle(self, vehicleID):
        try:
            arena = getattr(BigWorld.player(), 'arena', None)
            vehicles = getattr(arena, 'vehicles', {}) if arena is not None else {}
            data = vehicles.get(vehicleID) if hasattr(vehicles, 'get') else None
            if data is None and hasattr(vehicles, 'get'):
                data = vehicles.get(int(vehicleID))
            return self._vehicleDataGet(data, 'team', None)
        except Exception:
            return None

    def _isEnemyVehicle(self, vehicleID):
        team = self._teamForVehicle(vehicleID)
        return team is not None and self._playerTeam is not None and team != self._playerTeam

    def _isAllyVehicle(self, vehicleID):
        team = self._teamForVehicle(vehicleID)
        return team is not None and self._playerTeam is not None and team == self._playerTeam

    def _maxHealthForVehicle(self, vehicleID):
        try:
            arena = getattr(BigWorld.player(), 'arena', None)
            vehicles = getattr(arena, 'vehicles', None) if arena is not None else None
            data = vehicles.get(int(vehicleID)) if hasattr(vehicles, 'get') else None
            if data is None:
                return 0
            hp = self._vehicleDataGet(data, 'maxHealth', 0)
            if not hp:
                hp = self._vehicleDataGet(data, 'maxHp', 0)
            if not hp:
                hp = self._vehicleDataGet(data, 'health', 0)
            return int(hp or 0)
        except Exception:
            return 0

    def _calcTotalEnemiesHP(self):
        total = 0
        for vehicleID, data in self._vehicleItems():
            try:
                team = self._vehicleDataGet(data, 'team', None)
                if team is None or self._playerTeam is None or team == self._playerTeam:
                    continue
                hp = self._vehicleDataGet(data, 'maxHealth', 0)
                if not hp:
                    hp = self._vehicleDataGet(data, 'maxHp', 0)
                if not hp:
                    hp = self._vehicleDataGet(data, 'health', 0)
                total += max(0, int(hp or 0))
            except Exception:
                continue
        return total

    def _computeNeed(self, totalEnemiesHP):
        return max(
            MIN_GUN_DAMAGE,
            int(math.ceil(float(totalEnemiesHP) * DAMAGE_RATE))
        )

    def _scheduleRecalc(self):
        try:
            if self._recalcCallbackID is not None:
                BigWorld.cancelCallback(self._recalcCallbackID)
        except Exception:
            pass
        self._recalcCallbackID = BigWorld.callback(1.0, self._recalcTick)

    def _recalcTick(self):
        self._recalcCallbackID = None
        if not self._started:
            return
        totalEnemiesHP = self._calcTotalEnemiesHP()
        if totalEnemiesHP > self._totalEnemiesHP:
            self._syncMissingHealthEntries()
            self._totalEnemiesHP = totalEnemiesHP
            self._baseNeed = self._computeNeed(totalEnemiesHP)
            self._updateGunScore()
            self._checkWarning()
            self._publishState()
        self._scheduleRecalc()

    def _initHealthMap(self):
        self._healthMap = {}
        self._enemiesHP = 0
        for vehicleID, data in self._vehicleItems():
            try:
                hp = self._vehicleDataGet(data, 'health', 0)
                if not hp:
                    hp = self._vehicleDataGet(data, 'maxHealth', 0)
                if not hp:
                    hp = self._vehicleDataGet(data, 'maxHp', 0)
                hp = max(0, int(hp or 0))
                self._healthMap[int(vehicleID)] = hp
                if self._isEnemyVehicle(vehicleID):
                    self._enemiesHP += hp
            except Exception:
                continue

    def _syncMissingHealthEntries(self):
        for vehicleID, data in self._vehicleItems():
            try:
                vehicleID = int(vehicleID)
                if vehicleID in self._healthMap:
                    continue
                hp = self._vehicleDataGet(data, 'health', 0)
                if not hp:
                    hp = self._vehicleDataGet(data, 'maxHealth', 0)
                if not hp:
                    hp = self._vehicleDataGet(data, 'maxHp', 0)
                hp = max(0, int(hp or 0))
                self._healthMap[vehicleID] = hp
                if self._isEnemyVehicle(vehicleID):
                    self._enemiesHP += hp
            except Exception:
                continue

    def _sameVehicle(self, firstID, secondID):
        try:
            return int(firstID) == int(secondID)
        except Exception:
            return firstID == secondID

    def _topAllyDamage(self):
        topDamage = 0
        for vehicleID, damage in self._damageByVehicle.items():
            try:
                if self._sameVehicle(vehicleID, self._playerVehicleID):
                    continue
                if self._isAllyVehicle(vehicleID):
                    topDamage = max(topDamage, int(damage))
            except Exception:
                pass
        return topDamage

    def _updateGunScore(self):
        self._need = max(self._baseNeed, self._topAllyDamage())

    def _recordPlayerDamage(self, damage):
        try:
            damage = int(damage or 0)
        except Exception:
            damage = 0
        if damage <= 0 or not self._started:
            return
        self._current += damage
        self._checkWarning()
        self._publishState()

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
        if totalDamage > self._need:
            self._need = totalDamage

    def _updateEnemyHealth(self, targetID, damage):
        if not self._isEnemyVehicle(targetID):
            return False
        try:
            targetID = int(targetID)
            damage = max(0, int(damage or 0))
        except Exception:
            return False
        oldHP = self._healthMap.get(targetID, None)
        if oldHP is None:
            oldHP = self._maxHealthForVehicle(targetID)
        oldHP = max(0, int(oldHP or 0))
        newHP = max(0, oldHP - damage)
        self._healthMap[targetID] = newHP
        self._enemiesHP = max(0, self._enemiesHP - (oldHP - newHP))
        return True

    def _checkWarning(self):
        if self._warning:
            return
        if self._playerDead:
            self._warning = True
            return
        damageLeft = int(self._need) - int(self._current)
        if damageLeft > 0 and self._enemiesHP < damageLeft:
            self._warning = True

    def _onVehicleHealthChanged(self, targetID, attackerID, damage):
        if not self._started:
            return
        try:
            damage = int(damage or 0)
            if damage <= 0:
                return
            enemyDamaged = self._updateEnemyHealth(targetID, damage)
            if enemyDamaged:
                self._recordAllyDamage(attackerID, damage)
            self._checkWarning()
            self._publishState()
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

    def _processFeedbackOne(self, event):
        try:
            if not hasattr(event, 'getType'):
                return False
            if event.getType() != FEEDBACK_EVENT_ID.PLAYER_DAMAGED_HP_ENEMY:
                return False
            damage = self._damageFromObj(event.getExtra())
            if damage > 0:
                self._recordPlayerDamage(damage)
                return True
        except Exception:
            pass
        return False

    def _onPlayerFeedbackReceived(self, events):
        if not self._started:
            return
        try:
            if isinstance(events, (list, tuple)):
                for event in events:
                    self._processFeedbackOne(event)
            else:
                self._processFeedbackOne(events)
        except Exception as e:
            logger.error('[MainGun] feedback failed: %s', e)

    def _attachFeedback(self):
        try:
            player = BigWorld.player()
            provider = getattr(player, 'guiSessionProvider', None)
            shared = getattr(provider, 'shared', None) if provider is not None else None
            feedback = getattr(shared, 'feedback', None) if shared is not None else None
            if feedback is None:
                return False
            if self._feedbackCtrl is feedback and self._feedbackHooked:
                return True
            self._detachFeedback()
            event = getattr(feedback, 'onPlayerFeedbackReceived', None)
            if event is None:
                return False
            event += self._onPlayerFeedbackReceived
            self._feedbackCtrl = feedback
            self._feedbackHooked = True
            return True
        except Exception as e:
            logger.error('[MainGun] feedback attach failed: %s', e)
            return False

    def _detachFeedback(self):
        if self._feedbackCtrl is not None and self._feedbackHooked:
            try:
                event = getattr(self._feedbackCtrl, 'onPlayerFeedbackReceived', None)
                if event is not None:
                    event -= self._onPlayerFeedbackReceived
            except Exception:
                pass
        self._feedbackCtrl = None
        self._feedbackHooked = False

    def _attachArenaEvents(self):
        try:
            arena = getattr(BigWorld.player(), 'arena', None)
            if arena is None:
                return False
            self._detachArenaEvents()
            self._arena = arena
            healthEvent = getattr(arena, 'onVehicleHealthChanged', None)
            if healthEvent is not None:
                healthEvent += self._onVehicleHealthChanged
                self._healthHooked = True
            killEvent = getattr(arena, 'onVehicleKilled', None)
            if killEvent is not None:
                killEvent += self._onVehicleKilled
                self._killHooked = True
            return self._healthHooked
        except Exception as e:
            logger.error('[MainGun] arena events attach failed: %s', e)
            self._detachArenaEvents()
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
        self._arena = None
        self._healthHooked = False
        self._killHooked = False

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
            self._checkWarning()
            if changed or self._warning:
                self._publishState()
        except Exception as e:
            logger.error('[MainGun] kill event failed: %s', e)

    def _isTeamDamageLeader(self):
        return self._current >= self._topAllyDamage()

    def _publishState(self):
        remaining = max(0, int(self._need) - int(self._current))
        completed = self._need > 0 and self._current >= self._need
        leader = self._isTeamDamageLeader()
        obtained = bool(completed and leader)
        snapshot = (
            int(self._current),
            int(self._need),
            bool(completed),
            bool(leader),
            bool(obtained),
            bool(self._playerDead),
            bool(self._warning)
        )
        if snapshot == self._lastPublished:
            return
        self._lastPublished = snapshot
        self._panel.updateState({
            'current': int(self._current),
            'need': int(self._need),
            'remaining': int(remaining),
            'completed': bool(completed),
            'teamDamageLeader': bool(leader),
            'mainGunObtained': bool(obtained),
            'playerDead': bool(self._playerDead),
            'failed': bool(self._warning)
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

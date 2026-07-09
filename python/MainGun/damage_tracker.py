import time

import BigWorld
import constants
from Avatar import PlayerAvatar
from gui.battle_control.battle_constants import FEEDBACK_EVENT_ID

from .utils import logger

try:
    import Vehicle as VehicleModule
except Exception:
    VehicleModule = None


class DamageTracker(object):

    def __init__(self, panel):
        self._panel = panel
        self._started = False
        self._enemyHP = 0
        self._need = 0
        self._current = 0
        self._playerVehicleID = None
        self._playerTeam = None
        self._healthMap = {}
        self._damageByVehicle = {}
        self._recentDamage = []
        self._feedbackCtrl = None
        self._feedbackHookedNames = []
        self._startCallbackID = None
        self._recalcCallbackID = None
        self._playerDead = False
        self._arena = None
        self._killHooked = False

    def start(self):
        self._tryStartBattle(0)

    def stop(self):
        self._cancelCallbacks()
        self._detachFeedback()
        self._detachKillEvent()
        if self._started:
            self._panel.onBattleEnd()
        self._started = False
        self._enemyHP = 0
        self._need = 0
        self._current = 0
        self._playerVehicleID = None
        self._playerTeam = None
        self._healthMap = {}
        self._damageByVehicle = {}
        self._recentDamage = []
        self._playerDead = False

    def destroy(self):
        self.stop()

    def _cancelCallbacks(self):
        for cbid in (self._startCallbackID, self._recalcCallbackID):
            try:
                if cbid is not None:
                    BigWorld.cancelCallback(cbid)
            except Exception:
                pass
        self._startCallbackID = None
        self._recalcCallbackID = None

    def _tryStartBattle(self, attempt):
        self._startCallbackID = None
        if self._startBattleImpl():
            return
        if attempt < 20:
            self._startCallbackID = BigWorld.callback(0.5, lambda: self._tryStartBattle(attempt + 1))

    def _startBattleImpl(self):
        if not self._isAllowedBattle():
            return False
        self._captureContext()
        if self._playerVehicleID is None or self._playerTeam is None:
            return False
        enemyHP = self._calcEnemyHP()
        if enemyHP <= 0:
            return False
        self._enemyHP = enemyHP
        self._need = self._computeNeed(enemyHP)
        self._current = 0
        self._damageByVehicle = {}
        self._recentDamage = []
        self._playerDead = False
        self._initHealthMap()
        self._started = True
        self._panel.onBattleStart()
        self._attachFeedback()
        self._attachKillEvent()
        self._publishState()
        self._scheduleRecalc()
        logger.info('[MainGun] battle started: enemyHP=%d need=%d', self._enemyHP, self._need)
        return True

    def _isAllowedBattle(self):
        try:
            player = BigWorld.player()
            arena = getattr(player, 'arena', None)
            if arena is None:
                return False
            guiType = getattr(arena, 'guiType', None)
            allowed = []
            for attrName in ('RANDOM', 'MAPBOX'):
                value = getattr(constants.ARENA_GUI_TYPE, attrName, None)
                if value is not None:
                    allowed.append(value)
            return guiType in tuple(allowed)
        except Exception:
            return False

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
        for vid, data in self._vehicleItems():
            try:
                if int(vid) != int(vehicleID):
                    continue
                hp = self._vehicleDataGet(data, 'maxHealth', 0) or self._vehicleDataGet(data, 'maxHp', 0)
                if not hp:
                    hp = self._vehicleDataGet(data, 'health', 0)
                return int(hp or 0)
            except Exception:
                continue
        return 0

    def _calcEnemyHP(self):
        total = 0
        for vehicleID, data in self._vehicleItems():
            try:
                team = self._vehicleDataGet(data, 'team', None)
                if team is None or self._playerTeam is None or team == self._playerTeam:
                    continue
                hp = self._vehicleDataGet(data, 'maxHealth', 0) or self._vehicleDataGet(data, 'maxHp', 0)
                if not hp:
                    hp = self._vehicleDataGet(data, 'health', 0)
                total += max(0, int(hp or 0))
            except Exception:
                continue
        return total

    def _computeNeed(self, enemyHP):
        return int(max(1000, round(float(enemyHP) * 0.2)))

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
        enemyHP = self._calcEnemyHP()
        if enemyHP > 0 and enemyHP != self._enemyHP:
            self._enemyHP = enemyHP
            self._need = self._computeNeed(enemyHP)
            self._publishState()
        self._scheduleRecalc()

    def _initHealthMap(self):
        self._healthMap = {}
        for vehicleID, data in self._vehicleItems():
            try:
                hp = self._vehicleDataGet(data, 'health', 0) or self._vehicleDataGet(data, 'maxHealth', 0) or self._vehicleDataGet(data, 'maxHp', 0)
                if hp:
                    self._healthMap[int(vehicleID)] = int(hp)
            except Exception:
                continue

    def _isDuplicateDamage(self, vehicleID, damage):
        if vehicleID is None:
            return False
        now = time.time()
        fresh = []
        duplicate = False
        for item in self._recentDamage:
            try:
                ts, vid, dmg = item
                if now - ts <= 0.35:
                    fresh.append(item)
                    if int(vid) == int(vehicleID) and int(dmg) == int(damage):
                        duplicate = True
            except Exception:
                pass
        self._recentDamage = fresh
        if duplicate:
            return True
        self._recentDamage.append((now, int(vehicleID), int(damage)))
        return False

    def _addPlayerDamage(self, damage, vehicleID=None):
        try:
            damage = int(damage or 0)
        except Exception:
            damage = 0
        if damage <= 0 or not self._started:
            return
        if vehicleID is not None and self._isDuplicateDamage(vehicleID, damage):
            return
        self._current += damage
        if self._playerVehicleID is not None:
            self._damageByVehicle[self._playerVehicleID] = int(self._damageByVehicle.get(self._playerVehicleID, 0)) + damage
        self._publishState()

    def _addTeamDamage(self, attackerID, damage):
        try:
            damage = int(damage or 0)
        except Exception:
            damage = 0
        if damage <= 0 or attackerID is None:
            return
        if not self._isAllyVehicle(attackerID):
            return
        self._damageByVehicle[attackerID] = int(self._damageByVehicle.get(attackerID, 0)) + damage

    def _selectHealthCandidate(self, args, kwargs):
        candidates = []
        if len(args) >= 4:
            candidates.append((args[0], args[1], args[3]))
        if len(args) >= 3:
            candidates.append((args[0], args[1], args[2]))
        if len(args) >= 2:
            candidates.append((args[0], args[1], kwargs.get('attackerID', None)))
        for vid, hp, attacker in candidates:
            try:
                vid = int(vid)
                hp = int(hp)
                maxHP = self._maxHealthForVehicle(vid)
                if maxHP <= 0 or 0 <= hp <= maxHP:
                    return vid, hp, attacker
            except Exception:
                continue
        return (None, None, None)

    def processHealthChange(self, args, kwargs=None):
        if not self._started:
            return
        try:
            vehicleID, newHP, attackerID = self._selectHealthCandidate(tuple(args), kwargs or {})
            if vehicleID is None or newHP is None:
                return
            self._checkPlayerDeath(vehicleID, newHP)
            oldHP = self._healthMap.get(vehicleID, None)
            if oldHP is None:
                oldHP = self._maxHealthForVehicle(vehicleID)
            if oldHP is None or oldHP <= 0:
                self._healthMap[vehicleID] = int(newHP)
                return
            delta = int(oldHP) - int(newHP)
            self._healthMap[vehicleID] = int(newHP)
            if delta <= 0 or not self._isEnemyVehicle(vehicleID):
                return
            if attackerID is not None and self._playerVehicleID is not None and int(attackerID) == int(self._playerVehicleID):
                self._addPlayerDamage(delta, vehicleID)
            else:
                self._addTeamDamage(attackerID, delta)
                self._publishState()
        except Exception as e:
            logger.error('[MainGun] health change failed: %s', e)

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

    def _vehicleIDFromObj(self, obj):
        if obj is None:
            return None
        for name in ('vehicleID', 'vehicleId', 'targetID', 'targetId', 'entityID', 'entityId'):
            try:
                value = obj.get(name) if hasattr(obj, 'get') else getattr(obj, name)
                if value is not None:
                    return int(value)
            except Exception:
                pass
        for name in ('getVehicleID', 'getTargetID', 'getVehicleId', 'getTargetId'):
            try:
                getter = getattr(obj, name, None)
                if getter is not None:
                    value = getter()
                    if value is not None:
                        return int(value)
            except Exception:
                pass
        return None

    def _damageEventTypes(self):
        result = []
        for name in ('PLAYER_DAMAGED_HP_ENEMY', 'PLAYER_DAMAGED_HP_ENEMY_BY_EXPLOSION', 'PLAYER_DAMAGED_HP_ENEMY_BY_FIRE'):
            value = getattr(FEEDBACK_EVENT_ID, name, None)
            if value is not None and value not in result:
                result.append(value)
        return result

    def _processFeedbackOne(self, item):
        eventType = None
        extra = None
        try:
            if hasattr(item, 'getType'):
                eventType = item.getType()
                try:
                    extra = item.getExtra()
                except Exception:
                    extra = None
            elif isinstance(item, (tuple, list)) and item:
                eventType = item[0]
                extra = item
            else:
                eventType = item
        except Exception:
            return False
        if eventType not in self._damageEventTypes():
            return False
        damage = self._damageFromObj(extra)
        vehicleID = self._vehicleIDFromObj(item)
        if vehicleID is None:
            vehicleID = self._vehicleIDFromObj(extra)
        if damage > 0:
            self._addPlayerDamage(damage, vehicleID)
            return True
        return False

    def _onFeedback(self, *args):
        if not self._started:
            return
        try:
            if len(args) == 1 and isinstance(args[0], (list, tuple)):
                for item in args[0]:
                    self._processFeedbackOne(item)
                return
            if len(args) == 1:
                if self._processFeedbackOne(args[0]):
                    return
            self._processFeedbackOne(args)
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
            if self._feedbackCtrl is feedback and self._feedbackHookedNames:
                return True
            self._detachFeedback()
            names = []
            for name in ('onPlayerFeedbackReceived', 'onVehicleFeedbackReceived', 'onPlayerFeedbackUpdated', 'onVehicleFeedbackUpdated', 'onFeedbackReceived'):
                try:
                    event = getattr(feedback, name, None)
                    if event is not None:
                        event += self._onFeedback
                        names.append(name)
                except Exception:
                    pass
            self._feedbackCtrl = feedback
            self._feedbackHookedNames = names
            return bool(names)
        except Exception as e:
            logger.error('[MainGun] feedback attach failed: %s', e)
            return False

    def _detachFeedback(self):
        if self._feedbackCtrl is None:
            self._feedbackHookedNames = []
            return
        try:
            for name in list(self._feedbackHookedNames):
                try:
                    event = getattr(self._feedbackCtrl, name, None)
                    if event is not None:
                        event -= self._onFeedback
                except Exception:
                    pass
        except Exception:
            pass
        self._feedbackCtrl = None
        self._feedbackHookedNames = []

    def _attachKillEvent(self):
        try:
            arena = getattr(BigWorld.player(), 'arena', None)
            if arena is None:
                return False
            event = getattr(arena, 'onVehicleKilled', None)
            if event is not None and not self._killHooked:
                event += self._onVehicleKilled
                self._arena = arena
                self._killHooked = True
                return True
        except Exception as e:
            logger.error('[MainGun] kill event attach failed: %s', e)
        return False

    def _detachKillEvent(self):
        if not self._killHooked:
            return
        try:
            event = getattr(self._arena, 'onVehicleKilled', None)
            if event is not None:
                event -= self._onVehicleKilled
        except Exception:
            pass
        self._arena = None
        self._killHooked = False

    def _onVehicleKilled(self, targetID, *args):
        try:
            if not self._started or self._playerVehicleID is None:
                return
            if int(targetID) == int(self._playerVehicleID) and not self._playerDead:
                self._playerDead = True
                logger.info('[MainGun] player vehicle killed')
                self._publishState()
        except Exception as e:
            logger.error('[MainGun] kill event failed: %s', e)

    def _checkPlayerDeath(self, vehicleID, newHP):
        try:
            if self._playerVehicleID is None or self._playerDead:
                return
            if int(vehicleID) == int(self._playerVehicleID) and int(newHP) <= 0:
                self._playerDead = True
                logger.info('[MainGun] player vehicle dead (hp<=0)')
                self._publishState()
        except Exception:
            pass

    def _isTeamDamageLeader(self):
        if self._playerVehicleID is None or self._current <= 0:
            return False
        maxDamage = self._current
        for vehicleID, damage in self._damageByVehicle.items():
            try:
                if self._isAllyVehicle(vehicleID):
                    maxDamage = max(maxDamage, int(damage))
            except Exception:
                pass
        return self._current >= maxDamage

    def _publishState(self):
        remaining = max(0, int(self._need) - int(self._current))
        completed = self._need > 0 and self._current >= self._need
        leader = self._isTeamDamageLeader()
        self._panel.updateState({
            'current': int(self._current),
            'need': int(self._need),
            'remaining': int(remaining),
            'completed': bool(completed),
            'teamDamageLeader': bool(leader),
            'mainGunObtained': bool(completed and leader),
            'playerDead': bool(self._playerDead)
        })


g_tracker = None
_origEnterWorld = None
_origBecomeNonPlayer = None
_origHealthMethods = {}
_origVehicleHealthMethods = {}


def _makeHealthWrapper(original):

    def wrapper(self, *args, **kwargs):
        result = None
        error = None
        try:
            result = original(self, *args, **kwargs)
        except TypeError:
            try:
                result = original(self, *args)
            except Exception as e:
                error = e
        except Exception as e:
            error = e
        try:
            if g_tracker is not None:
                g_tracker.processHealthChange(args, kwargs)
        except Exception:
            pass
        if error is not None:
            raise error
        return result

    return wrapper


def _makeVehicleHealthWrapper(original):

    def wrapper(self, *args, **kwargs):
        result = None
        error = None
        try:
            result = original(self, *args, **kwargs)
        except TypeError:
            try:
                result = original(self, *args)
            except Exception as e:
                error = e
        except Exception as e:
            error = e
        try:
            vehicleID = getattr(self, 'id', None)
            if vehicleID is not None and g_tracker is not None:
                g_tracker.processHealthChange((vehicleID,) + tuple(args), kwargs)
        except Exception:
            pass
        if error is not None:
            raise error
        return result

    return wrapper


def _installHealthHooks():
    for name in ('updateVehicleHealth', 'onVehicleHealthChanged', 'vehicle_onHealthChanged'):
        try:
            if hasattr(PlayerAvatar, name) and name not in _origHealthMethods:
                original = getattr(PlayerAvatar, name)
                _origHealthMethods[name] = original
                setattr(PlayerAvatar, name, _makeHealthWrapper(original))
        except Exception:
            pass
    try:
        vehicleClass = getattr(VehicleModule, 'Vehicle', None) if VehicleModule is not None else None
        if vehicleClass is not None:
            for name in ('onHealthChanged', 'healthChanged', 'setHealth'):
                try:
                    key = 'Vehicle.%s' % name
                    if hasattr(vehicleClass, name) and key not in _origVehicleHealthMethods:
                        original = getattr(vehicleClass, name)
                        _origVehicleHealthMethods[key] = (vehicleClass, name, original)
                        setattr(vehicleClass, name, _makeVehicleHealthWrapper(original))
                except Exception:
                    pass
    except Exception:
        pass


def _uninstallHealthHooks():
    for name, original in _origHealthMethods.items():
        try:
            setattr(PlayerAvatar, name, original)
        except Exception:
            pass
    _origHealthMethods.clear()
    for key, data in _origVehicleHealthMethods.items():
        try:
            cls, name, original = data
            setattr(cls, name, original)
        except Exception:
            pass
    _origVehicleHealthMethods.clear()


def _onAvatarEnterWorld(self, *args, **kwargs):
    result = None
    try:
        result = _origEnterWorld(self, *args, **kwargs)
    except TypeError:
        result = _origEnterWorld(self)
    try:
        if g_tracker is not None:
            g_tracker.start()
    except Exception as e:
        logger.error('[MainGun] start failed: %s', e)
    return result


def _onAvatarBecomeNonPlayer(self, *args, **kwargs):
    try:
        if g_tracker is not None:
            g_tracker.stop()
    except Exception:
        pass
    try:
        return _origBecomeNonPlayer(self, *args, **kwargs)
    except TypeError:
        return _origBecomeNonPlayer(self)


def initialize(panel):
    global g_tracker
    global _origEnterWorld
    global _origBecomeNonPlayer
    if g_tracker is None:
        g_tracker = DamageTracker(panel)
    _installHealthHooks()
    if getattr(PlayerAvatar, '_under_pressure_maingun_patched', False):
        return
    _origEnterWorld = PlayerAvatar.onEnterWorld
    _origBecomeNonPlayer = PlayerAvatar.onBecomeNonPlayer
    PlayerAvatar.onEnterWorld = _onAvatarEnterWorld
    PlayerAvatar.onBecomeNonPlayer = _onAvatarBecomeNonPlayer
    PlayerAvatar._under_pressure_maingun_patched = True
    logger.info('[MainGun] tracker initialized')


def finalize():
    global g_tracker
    global _origEnterWorld
    global _origBecomeNonPlayer
    try:
        if g_tracker is not None:
            g_tracker.destroy()
    except Exception:
        pass
    g_tracker = None
    try:
        if getattr(PlayerAvatar, '_under_pressure_maingun_patched', False):
            PlayerAvatar.onEnterWorld = _origEnterWorld
            PlayerAvatar.onBecomeNonPlayer = _origBecomeNonPlayer
            PlayerAvatar._under_pressure_maingun_patched = False
    except Exception:
        pass
    _uninstallHealthHooks()

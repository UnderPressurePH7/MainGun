(function () {
    'use strict';

    var root = document.getElementById('main-gun-root');
    var contentEl = document.getElementById('main-gun-content');
    var panelEl = document.getElementById('main-gun-panel');
    var labelEl = document.getElementById('main-gun-label');
    var remainingEl = document.getElementById('main-gun-remaining');
    var statusEl = document.getElementById('main-gun-status');
    var selectorEl = document.getElementById('main-gun-mode-selector');
    var iconEl = document.getElementById('main-gun-icon');
    var checkEl = document.getElementsByClassName('main-gun-status-check')[0];
    var crossEl = document.getElementsByClassName('main-gun-status-cross')[0];
    var modeButtons = selectorEl.getElementsByClassName('main-gun-mode-button');
    var payload = {};
    var lastPayload = null;
    var lastReportedSize = null;
    var pendingResize = null;
    var resizeRetryTimer = null;
    var resizeRetryLogged = false;
    var measureFrame = null;
    var settleFrame = null;
    var renderRevision = 0;
    var layoutReady = false;
    var initialized = false;
    function debug(message) {
        try {
            if (window.model && typeof window.model.onDebug === 'function') {
                window.model.onDebug({ message: String(message) });
            }
        } catch (e) {}
    }


    function sendCmd(name, value) {
        try {
            if (window.model && typeof window.model.onCmd === 'function') {
                window.model.onCmd({
                    name: String(name),
                    value: value === undefined ? '' : String(value)
                });
                return true;
            }
        } catch (e) {
            debug('command ' + name + ' failed: ' + e);
        }
        return false;
    }

    function toNumber(value, fallback) {
        var parsed = parseFloat(value);
        return isNaN(parsed) ? fallback : parsed;
    }

    function toInt(value, fallback) {
        var parsed = parseInt(value, 10);
        return isNaN(parsed) ? fallback : parsed;
    }

    function formatNumber(value) {
        value = Math.max(0, toInt(value, 0));
        return String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    }


    function setClass(element, name, enabled) {
        if (enabled) element.classList.add(name);
        else element.classList.remove(name);
    }
    function syncVisibility() {
        setClass(root, 'main-gun-hidden', payload.visible !== true || !layoutReady);
    }
    function revealAfterResize(key) {
        requestAnimationFrame(function () {
            if (key !== lastReportedSize) return;
            layoutReady = true;
            syncVisibility();
        });
    }


    function clientSize() {
        try {
            if (window.viewEnv && viewEnv.getClientSizePx) {
                var s = viewEnv.getClientSizePx();
                if (s && s.width > 0 && s.height > 0) {
                    return { width: s.width, height: s.height };
                }
            }
        } catch (e) {}
        return {
            width: document.documentElement.clientWidth || window.innerWidth || 1920,
            height: document.documentElement.clientHeight || window.innerHeight || 1080
        };
    }

    function remScale(payloadScale) {
        var uiScale = toNumber(payloadScale, 1) || 1;
        try {
            if (window.viewEnv && viewEnv.remToPx) {
                var px = viewEnv.remToPx(1);
                if (px > 0) return px;
            }
        } catch (e) {}
        if (uiScale > 0) return uiScale;
        var size = clientSize();
        return Math.min(size.width / 1920, size.height / 1080) || 1;
    }

    function reportSize(width, height, panelWidth, panelHeight) {
        var w = Math.max(1, Math.round(width));
        var h = Math.max(1, Math.round(height));
        var pw = Math.max(1, Math.round(panelWidth));
        var ph = Math.max(1, Math.round(panelHeight));
        var key = w + 'x' + h + 'x' + pw + 'x' + ph;
        if (key === lastReportedSize) {
            if (layoutReady) syncVisibility();
            else revealAfterResize(key);
            return;
        }
        var applied = false;
        try {
            if (window.viewEnv && typeof viewEnv.resizeViewPx === 'function') {
                viewEnv.resizeViewPx(w, h);
                applied = true;
            }
        } catch (e) {
            debug('resizeViewPx failed: ' + e);
        }
        if (!applied) {
            pendingResize = [w, h, pw, ph];
            if (!resizeRetryLogged) {
                resizeRetryLogged = true;
                debug('resizeViewPx unavailable, retrying ' + key);
            }
            if (resizeRetryTimer === null) {
                resizeRetryTimer = window.setTimeout(function () {
                    resizeRetryTimer = null;
                    var size = pendingResize;
                    pendingResize = null;
                    if (size) {
                        reportSize(size[0], size[1], size[2], size[3]);
                    }
                }, 250);
            }
            return;
        }
        pendingResize = null;
        lastReportedSize = key;
        resizeRetryLogged = false;
        sendCmd('onSize', key);
        revealAfterResize(key);
    }

    function measureAndReport() {
        var rem = remScale(payload.scale);
        var paddingX = 8 * rem * 2;
        var borderX = 1 * rem * 2;
        var displayMode = Math.max(1, Math.min(2, toInt(payload.displayMode, 1)));

        var contentRect = contentEl.getBoundingClientRect();
        var contentWidth = contentRect.width;
        var panelWidth = Math.ceil(contentWidth + paddingX + borderX);
        var panelHeight = Math.ceil(Math.max(panelEl.getBoundingClientRect().height,
            displayMode === 2 ? 42 * rem : 26 * rem));
        var selectorWidth = 53 * rem;
        var selectorHeight = 25 * rem;
        var selectorGap = 5 * rem;
        var width = Math.ceil(Math.max(panelWidth, selectorWidth));
        var height = Math.ceil(panelHeight + selectorGap + selectorHeight);
        root.style.width = width + 'px';
        root.style.height = height + 'px';
        panelEl.style.width = panelWidth + 'px';
        selectorEl.style.left = Math.max(0, Math.round((width - selectorWidth) * 0.5)) + 'px';
        selectorEl.style.top = Math.round(panelHeight + selectorGap) + 'px';
        void root.offsetHeight;

        reportSize(width, height, panelWidth, panelHeight);
    }

    function scheduleMeasure() {
        var revision = ++renderRevision;
        if (measureFrame !== null) {
            cancelAnimationFrame(measureFrame);
        }
        if (settleFrame !== null) {
            cancelAnimationFrame(settleFrame);
        }
        measureFrame = requestAnimationFrame(function () {
            measureFrame = null;
            settleFrame = requestAnimationFrame(function () {
                settleFrame = null;
                if (revision !== renderRevision) return;
                measureAndReport();
            });
        });
    }

    function readPayload() {
        var raw = window.model && window.model.payload ? String(window.model.payload) : '';
        if (raw === lastPayload) {
            return;
        }
        lastPayload = raw;
        try {
            payload = JSON.parse(raw || '{}');
        } catch (e) {
            payload = {};
            debug('payload parse failed: ' + e);
        }
    }

    function render() {
        readPayload();
        var state = payload.state || {};
        var l10n = payload.l10n || {};
        var scale = remScale(payload.scale);
        var obtained = !!state.mainGunObtained;
        var dead = !!state.playerDead;
        var failed = dead && !obtained;
        var displayMode = Math.max(1, Math.min(2, toInt(payload.displayMode, 1)));
        var extended = !!payload.extendedInfo;

        document.documentElement.style.fontSize = scale + 'px';
        labelEl.textContent = (l10n.mainGun || 'Main Gun') + ':';
        remainingEl.textContent = formatNumber(state.remaining);
        setClass(labelEl, 'main-gun-label-hidden', displayMode === 2);
        setClass(iconEl, 'main-gun-icon-visible', displayMode === 2);
        setClass(remainingEl, 'main-gun-remaining-icon-mode', displayMode === 2);
        setClass(selectorEl, 'main-gun-mode-selector-visible', extended);
        setClass(statusEl, 'main-gun-status-visible', obtained || failed);
        setClass(checkEl, 'main-gun-status-svg-visible', obtained);
        setClass(crossEl, 'main-gun-status-svg-visible', failed);

        if (obtained) {
            labelEl.classList.add('main-gun-label-done');
            labelEl.classList.remove('main-gun-label-fail');
            setClass(remainingEl, 'main-gun-remaining-done', displayMode === 2);
            remainingEl.classList.remove('main-gun-remaining-fail');
        } else if (failed) {
            labelEl.classList.add('main-gun-label-fail');
            labelEl.classList.remove('main-gun-label-done');
            setClass(remainingEl, 'main-gun-remaining-fail', displayMode === 2);
            remainingEl.classList.remove('main-gun-remaining-done');
        } else {
            labelEl.classList.remove('main-gun-label-done');
            labelEl.classList.remove('main-gun-label-fail');
            remainingEl.classList.remove('main-gun-remaining-done');
            remainingEl.classList.remove('main-gun-remaining-fail');
        }

        for (var i = 0; i < modeButtons.length; i++) {
            setClass(modeButtons[i], 'active', toInt(modeButtons[i].getAttribute('data-mode'), 0) === displayMode);
        }

        syncVisibility();

        scheduleMeasure();
    }

    function poll() {
        var raw = window.model && window.model.payload ? String(window.model.payload) : '';
        if (raw !== lastPayload) {
            render();
        }
    }

    function initialize() {
        if (initialized) return;
        initialized = true;

        for (var i = 0; i < modeButtons.length; i++) {
            modeButtons[i].addEventListener('click', function () {
                sendCmd('onModeChanged', this.getAttribute('data-mode'));
            });
        }
        iconEl.addEventListener('error', function () {
            debug('WoT Main Gun achievement icon failed to load');
            scheduleMeasure();
        });
        iconEl.addEventListener('load', scheduleMeasure);
        render();
        if (window.engine) {
            window.engine.on('viewEnv.onDataChanged', render);
            window.engine.on('self.onScaleUpdated', render);
            window.engine.on('clientResized', render);
        }
        if (window.viewEnv && typeof viewEnv.addDataChangedCallback === 'function') {
            try {
                viewEnv.addDataChangedCallback('model', 0, true);
            } catch (e) {}
        }
        try {
            window.addEventListener('resize', render);
        } catch (e) {}
        try {
            if (document.fonts && document.fonts.ready && typeof document.fonts.ready.then === 'function') {
                document.fonts.ready.then(scheduleMeasure);
            }
        } catch (e) {}
        window.setTimeout(scheduleMeasure, 300);
        window.setTimeout(scheduleMeasure, 1000);
        window.setInterval(poll, 200);
        if (window.model && typeof window.model.onReady === 'function') {
            window.model.onReady({});
        }
    }

    function afterFrames() {
        requestAnimationFrame(function () {
            requestAnimationFrame(initialize);
        });
    }

    if (window.engine && window.engine.whenReady) {
        var domReady = window.isDomBuilt ? Promise.resolve() : new Promise(function (resolve) {
            window.engine.on('self.onDomBuilt', resolve);
        });
        Promise.all([window.engine.whenReady, domReady]).then(afterFrames);
    } else {
        afterFrames();
    }
}());

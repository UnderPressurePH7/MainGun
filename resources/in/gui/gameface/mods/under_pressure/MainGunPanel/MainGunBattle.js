(function () {
    'use strict';

    var root = document.getElementById('main-gun-root');
    var contentEl = document.getElementById('main-gun-content');
    var labelEl = document.getElementById('main-gun-label');
    var remainingEl = document.getElementById('main-gun-remaining');
    var payload = {};
    var lastPayload = null;
    var lastReportedSize = null;

    function sendCmd(name, value) {
        try {
            if (window.model && typeof window.model.onCmd === 'function') {
                window.model.onCmd({
                    name: String(name),
                    value: value === undefined ? '' : String(value)
                });
            }
        } catch (e) {}
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
        var size = clientSize();
        var responsive = Math.min(size.width / 1920, size.height / 1080) || 1;
        return responsive * uiScale;
    }

    function reportSize(width, height) {
        var w = Math.max(1, Math.round(width));
        var h = Math.max(1, Math.round(height));
        var key = w + 'x' + h;
        if (key === lastReportedSize) {
            return;
        }
        try {
            if (window.viewEnv && typeof viewEnv.resizeViewPx === 'function') {
                viewEnv.resizeViewPx(w, h);
            }
        } catch (e) {}
        lastReportedSize = key;
        sendCmd('onSize', key);
    }

    function measureAndReport() {
        var rem = remScale(payload.scale);
        var paddingX = 8 * rem * 2;
        var borderX = 1 * rem * 2;

        // The whole caption lives on one inline line inside #main-gun-content,
        // an inline-block that hugs its content regardless of the container
        // width. Measure it and size the panel box around it explicitly, since
        // Gameface does not shrink-wrap the flex container on its own.
        var contentWidth = contentEl.getBoundingClientRect().width;
        var width = Math.ceil(contentWidth + paddingX + borderX);
        root.style.width = width + 'px';
        void root.offsetWidth;

        var rect = root.getBoundingClientRect();
        reportSize(rect.width, rect.height);
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
        }
    }

    function render() {
        readPayload();
        var state = payload.state || {};
        var l10n = payload.l10n || {};
        var scale = remScale(payload.scale);
        var obtained = !!state.mainGunObtained;
        var dead = !!state.playerDead;
        var remainingVal = toInt(state.remaining, 0);

        document.documentElement.style.fontSize = scale + 'px';
        labelEl.textContent = l10n.mainGun || 'Main Gun';
        remainingEl.textContent = formatNumber(state.remaining);

        if (obtained) {
            labelEl.classList.add('main-gun-label-done');
            labelEl.classList.remove('main-gun-label-fail');
        } else if (dead && remainingVal > 0) {
            labelEl.classList.add('main-gun-label-fail');
            labelEl.classList.remove('main-gun-label-done');
        } else {
            labelEl.classList.remove('main-gun-label-done');
            labelEl.classList.remove('main-gun-label-fail');
        }

        if (payload.visible === false) {
            root.classList.add('main-gun-hidden');
        } else {
            root.classList.remove('main-gun-hidden');
        }

        measureAndReport();
    }

    function poll() {
        var raw = window.model && window.model.payload ? String(window.model.payload) : '';
        if (raw !== lastPayload) {
            render();
        }
    }

    function initialize() {
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
                document.fonts.ready.then(measureAndReport);
            }
        } catch (e) {}
        window.setTimeout(measureAndReport, 300);
        window.setTimeout(measureAndReport, 1000);
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

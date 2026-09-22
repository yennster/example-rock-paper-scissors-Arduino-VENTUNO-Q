// SPDX-FileCopyrightText: Copyright (C) Arduino s.r.l. and/or its affiliated companies
//
// SPDX-License-Identifier: MPL-2.0

var EMOJIS = {
    Rock:     '\uD83E\uDEA8',
    Paper:    '\uD83D\uDCC4',
    Scissors: '\u2702\uFE0F'
};

/* Per-class colour used for the bounding boxes and the translucent wash over
   the live feed. Keep these in sync with each other. */
var CLASS_COLORS = {
    rock:     { rgb: '245, 158, 11'  },
    paper:    { rgb: '59, 130, 246'  },
    scissors: { rgb: '168, 85, 247'  }
};
var DEFAULT_COLOR = { rgb: '74, 222, 128' };

function colorFor(label) {
    return CLASS_COLORS[String(label || '').toLowerCase()] || DEFAULT_COLOR;
}

var RESULT_MSG = {
    human:        'You win!',
    arduino:      'Arduino wins!',
    draw:         'Draw!',
    no_detection: 'No gesture detected'
};

var prevState = '';
var lastState = null;

/* ── WebUI connection ── */
var ui = new WebUI();
ui.on_connect(function () { console.log('Connected to the server'); });
ui.on_disconnect(function () { console.log('Disconnected from the server'); });
ui.on_message('state', update); // server pushes state on every change — no polling needed
ui.on_message('detections', onDetections); // high-rate channel: bounding boxes only

/* ── Live camera feed ── */
var camFeed    = document.getElementById('cameraFeed');
var camCanvas  = document.getElementById('boxCanvas');
var camStatus  = document.getElementById('cameraStatus');
var camHead    = document.getElementById('cameraHead');
var camHint    = document.getElementById('cameraHint');
var latestBoxes = [];
var camStreaming = false;
var camRetry = null;

function startCameraFeed() {
    if (camRetry) { clearTimeout(camRetry); camRetry = null; }
    /* Cache-buster: a re-used MJPEG URL can be served from the bfcache as a
       dead connection after a reconnect. */
    camFeed.src = 'camera?t=' + Date.now();
}

camFeed.addEventListener('load', function () {
    /* MJPEG fires 'load' once per delivered frame — the first one means the
       stream is alive. */
    if (!camStreaming) {
        camStreaming = true;
        camStatus.classList.remove('show');
        camHead.classList.add('streaming');
        camHint.textContent = 'streaming';
    }
    drawBoxes();
});

camFeed.addEventListener('error', function () {
    camStreaming = false;
    camHead.classList.remove('streaming');
    camHint.textContent = 'reconnecting…';
    camStatus.textContent = 'Waiting for the camera feed…';
    camStatus.classList.add('show');
    if (!camRetry) camRetry = setTimeout(startCameraFeed, 2000);
});

window.addEventListener('resize', drawBoxes);

/* Bounding boxes arrive in the pixel coordinates of the very frame being
   streamed (the model runner rescales them to the preview resolution), so the
   only mapping needed is the letterboxing introduced by object-fit: contain. */
function stageGeometry() {
    var nw = camFeed.naturalWidth, nh = camFeed.naturalHeight;
    var cw = camFeed.clientWidth,  ch = camFeed.clientHeight;
    if (!nw || !nh || !cw || !ch) return null;
    var scale = Math.min(cw / nw, ch / nh);
    return {
        scale: scale,
        offsetX: (cw - nw * scale) / 2,
        offsetY: (ch - nh * scale) / 2,
        width: cw,
        height: ch
    };
}

function drawBoxes() {
    var geo = stageGeometry();
    if (!geo) return;

    var dpr = window.devicePixelRatio || 1;
    if (camCanvas.width !== Math.round(geo.width * dpr) ||
        camCanvas.height !== Math.round(geo.height * dpr)) {
        camCanvas.width  = Math.round(geo.width * dpr);
        camCanvas.height = Math.round(geo.height * dpr);
    }

    var ctx = camCanvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, geo.width, geo.height);

    for (var i = 0; i < latestBoxes.length; i++) {
        var b = latestBoxes[i];
        if (!b.box || b.box.length !== 4) continue;

        var x = geo.offsetX + b.box[0] * geo.scale;
        var y = geo.offsetY + b.box[1] * geo.scale;
        var w = (b.box[2] - b.box[0]) * geo.scale;
        var h = (b.box[3] - b.box[1]) * geo.scale;
        if (w <= 0 || h <= 0) continue;

        var rgb = colorFor(b.label).rgb;

        ctx.fillStyle = 'rgba(' + rgb + ', 0.15)';
        ctx.fillRect(x, y, w, h);

        ctx.strokeStyle = 'rgb(' + rgb + ')';
        ctx.lineWidth = 3;
        ctx.strokeRect(x, y, w, h);

        var text = b.label.toUpperCase() + '  ' + Math.round(b.confidence * 100) + '%';
        ctx.font = '600 13px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
        var pad = 6;
        var tw = ctx.measureText(text).width;
        var th = 20;
        var ty = y - th >= 0 ? y - th : y;  /* flip inside the box near the top edge */

        ctx.fillStyle = 'rgb(' + rgb + ')';
        ctx.fillRect(x, ty, tw + pad * 2, th);
        ctx.fillStyle = '#0b0b0b';
        ctx.textBaseline = 'middle';
        ctx.fillText(text, x + pad, ty + th / 2);
    }
}

function onDetections(msg) {
    latestBoxes = (msg && msg.boxes) || [];
    drawBoxes();
}

/* The translucent class overlay: a colour wash plus a see-through emoji, so
   the camera stays visible underneath. */
function updateCameraOverlay(s) {
    var overlay = document.getElementById('cameraOverlay');
    var tint    = document.getElementById('cameraTint');
    var emoji   = document.getElementById('cameraEmoji');
    var label   = document.getElementById('cameraLabel');

    if (s.detection && s.confidence > 0) {
        var cap = s.detection.charAt(0).toUpperCase() + s.detection.slice(1);
        var rgb = colorFor(s.detection).rgb;
        overlay.className = 'camera-overlay has-detection';
        tint.style.background = 'rgba(' + rgb + ', 0.16)';
        tint.style.boxShadow = 'inset 0 0 0 3px rgba(' + rgb + ', 0.6), ' +
                               'inset 0 0 34px rgba(' + rgb + ', 0.22)';
        emoji.textContent = EMOJIS[cap] || '\u270B';
        label.textContent = (s.locked ? cap + ' — captured' : cap) +
                            '  ·  ' + Math.round(s.confidence * 100) + '%';
    } else {
        overlay.className = 'camera-overlay';
        tint.style.background = 'transparent';
        tint.style.boxShadow = 'none';
        emoji.textContent = '\u270B';
        label.textContent = s.state === 'countdown' ? 'Get ready…' : 'Show your hand';
    }
}

/* ── Update UI ── */
function update(s) {
    lastState = s;
    document.getElementById('humanScore').textContent = s.humanWins;
    document.getElementById('arduinoScore').textContent = s.arduinoWins;

    var emoji = document.getElementById('moveEmoji');
    var name  = document.getElementById('moveName');
    var btn   = document.getElementById('playBtn');

    btn.textContent = s.auto ? 'Pause' : (s.round > 0 ? 'Resume Match' : 'Start Match');
    btn.className = s.auto ? 'btn-play playing' : 'btn-play';

    document.getElementById('playHint').textContent = s.auto
        ? 'Rounds keep coming — hold your gesture until the countdown hits zero.'
        : 'Rounds run back to back — your gesture is read the moment the countdown hits zero.';

    if (s.cameraAvailable === false && !camStreaming) {
        camStatus.textContent = 'Camera feed unavailable — the detection brick is not running.';
        camStatus.classList.add('show');
        camHint.textContent = 'offline';
    }

    /* ── Detection panel ── */
    var dPanel = document.getElementById('detectPanel');
    var dEmoji = document.getElementById('detectEmoji');
    var dLabel = document.getElementById('detectLabel');
    var dConf  = document.getElementById('detectConf');

    if (s.detection && s.confidence > 0) {
        var cap = s.detection.charAt(0).toUpperCase() + s.detection.slice(1);
        dPanel.className = s.locked ? 'detect-display locked' : 'detect-display active';
        dEmoji.textContent = EMOJIS[cap] || '\u270B';
        dLabel.textContent = s.locked ? cap + ' — captured!' : cap;
        dConf.textContent = Math.round(s.confidence * 100) + '% confidence';
    } else if (s.locked) {
        dPanel.className = 'detect-display locked';
        dEmoji.textContent = '\u270B';
        dLabel.textContent = 'No gesture captured';
        dConf.innerHTML = '&nbsp;';
    } else {
        dPanel.className = 'detect-display';
        dEmoji.textContent = '\u270B';
        dLabel.textContent = s.state === 'countdown' ? 'Get ready…' : 'Show your hand';
        dConf.innerHTML = '&nbsp;';
    }

    updateCameraOverlay(s);

    /* ── Arduino panel ── */
    if (s.state === 'countdown' && s.countdown != null) {
        emoji.textContent = s.countdown;
        emoji.className = 'move-emoji countdown-num';
        name.textContent = 'get ready';
        hideBanner();
    }
    else if (s.state === 'shoot') {
        emoji.textContent = EMOJIS[s.arduinoMove] || '\u2753';
        emoji.className = 'move-emoji countdown-num';
        name.textContent = 'shoot!';
        hideBanner();
    }
    else if ((s.state === 'evaluating' || s.state === 'result') && s.winner) {
        emoji.textContent = EMOJIS[s.arduinoMove] || '?';
        emoji.className = 'move-emoji';
        name.textContent = s.arduinoMove || '';

        var cls = s.winner === 'human' ? 'human' :
                  s.winner === 'arduino' ? 'arduino' :
                  s.winner === 'draw' ? 'draw' : 'error';

        var msg = RESULT_MSG[s.winner] || '';
        if (s.winner === 'human') {
            msg += ' ' + (EMOJIS[s.humanMove] || '') + ' ' +
                   (s.humanMove || '') + ' beats ' +
                   (EMOJIS[s.arduinoMove] || '') + ' ' +
                   (s.arduinoMove || '');
        } else if (s.winner === 'arduino') {
            msg += ' ' + (EMOJIS[s.arduinoMove] || '') + ' ' +
                   (s.arduinoMove || '') + ' beats ' +
                   (EMOJIS[s.humanMove] || '') + ' ' +
                   (s.humanMove || '');
        } else if (s.winner === 'draw') {
            msg += ' Both chose ' + (EMOJIS[s.arduinoMove] || '') +
                   ' ' + (s.arduinoMove || '');
        }
        showBanner(msg, cls);
    }
    else {
        emoji.textContent = '\u2753';
        emoji.className = 'move-emoji';
        name.textContent = 'waiting';
        if (s.state === 'idle' && prevState === 'result') {
            /* keep banner visible until the next round starts */
        } else if (s.state === 'idle' && s.round === 0) {
            hideBanner();
        }
    }

    prevState = s.state;

    /* ── Live commentary ── */
    updateCommentary(s.commentary, s.commentating);

    /* ── History ── */
    updateHistory(s.history);
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

var renderedCommentary = [];

function sameLines(a, b) {
    if (a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) {
        if (a[i] !== b[i]) return false;
    }
    return true;
}

function updateCommentary(lines, commentating) {
    document.getElementById('onAir').className = commentating ? 'on-air live' : 'on-air';

    lines = lines || [];
    var feed = document.getElementById('commentaryFeed');
    var empty = document.getElementById('commentaryEmpty');

    /* Only touch the DOM when the feed actually changed — rebuilding on every
       push would restart the slide-in animation and cause flicker. */
    if (sameLines(lines, renderedCommentary)) return;

    if (lines.length === 0) {
        feed.innerHTML = '';
        empty.style.display = 'block';
        renderedCommentary = [];
        return;
    }

    var prev = {};
    for (var j = 0; j < renderedCommentary.length; j++) prev[renderedCommentary[j]] = true;

    empty.style.display = 'none';
    var html = '';
    for (var i = 0; i < lines.length; i++) {
        var cls = [];
        if (i === 0) cls.push('latest');
        if (!prev[lines[i]]) cls.push('new');       /* animate only fresh lines */
        html += '<li' + (cls.length ? ' class="' + cls.join(' ') + '"' : '') + '>' +
                escapeHtml(lines[i]) + '</li>';
    }
    feed.innerHTML = html;
    renderedCommentary = lines.slice();
}

function showBanner(text, cls) {
    var b = document.getElementById('resultBanner');
    b.textContent = text;
    b.className = 'result-banner show ' + cls;
}

function hideBanner() {
    document.getElementById('resultBanner').className = 'result-banner';
}

function updateHistory(history) {
    var tbody = document.getElementById('histBody');
    var noMsg = document.getElementById('noHist');
    if (!history || history.length === 0) {
        tbody.innerHTML = '';
        noMsg.style.display = 'block';
        return;
    }
    noMsg.style.display = 'none';
    var html = '';
    for (var i = 0; i < history.length; i++) {
        var r = history[i];
        var cls = r.winner === 'human' ? 'res-win' :
                  r.winner === 'arduino' ? 'res-lose' :
                  r.winner === 'draw' ? 'res-draw' : 'res-none';
        var resText = r.winner === 'human' ? 'Win' :
                      r.winner === 'arduino' ? 'Loss' :
                      r.winner === 'draw' ? 'Draw' : 'N/A';
        var hm = r.humanMove ? (EMOJIS[r.humanMove] || '') + ' ' + r.humanMove : '\u2014';
        var am = r.arduinoMove ? (EMOJIS[r.arduinoMove] || '') + ' ' + r.arduinoMove : '\u2014';
        html += '<tr><td>' + r.round + '</td><td>' + hm +
                '</td><td>' + am + '</td><td class="' + cls + '">' + resText + '</td></tr>';
    }
    tbody.innerHTML = html;
}

/* ── Actions ── */
function togglePlay() {
    var playing = lastState && lastState.auto;
    if (playing) {
        ui.send_message('pause');
    } else {
        hideBanner();
        ui.send_message('start');
    }
    // the next 'state' push repaints the button — no optimistic toggle needed
}

function resetGame() {
    hideBanner();
    ui.send_message('reset'); // next 'state' push repaints scores/history/commentary
}

startCameraFeed();

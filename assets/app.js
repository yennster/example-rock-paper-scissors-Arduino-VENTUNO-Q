// SPDX-FileCopyrightText: Copyright (C) Arduino s.r.l. and/or its affiliated companies
//
// SPDX-License-Identifier: MPL-2.0

var EMOJIS = {
    Rock:     '\uD83E\uDEA8',
    Paper:    '\uD83D\uDCC4',
    Scissors: '\u2702\uFE0F'
};

var RESULT_MSG = {
    human:        'You win!',
    arduino:      'Arduino wins!',
    draw:         'Draw!',
    no_detection: 'No gesture detected'
};

var prevState = '';

/* ── WebUI connection ── */
var ui = new WebUI();
ui.on_connect(function () { console.log('Connected to the server'); });
ui.on_disconnect(function () { console.log('Disconnected from the server'); });
ui.on_message('state', update); // server pushes state on every change — no polling needed

/* ── Update UI ── */
function update(s) {
    document.getElementById('humanScore').textContent = s.humanWins;
    document.getElementById('arduinoScore').textContent = s.arduinoWins;

    var emoji = document.getElementById('moveEmoji');
    var name  = document.getElementById('moveName');
    var btn   = document.getElementById('playBtn');

    btn.disabled = (s.state !== 'idle');

    /* ── Detection panel ── */
    var dPanel = document.getElementById('detectPanel');
    var dEmoji = document.getElementById('detectEmoji');
    var dLabel = document.getElementById('detectLabel');
    var dConf  = document.getElementById('detectConf');
    var isLocked = (s.state === 'countdown' || s.state === 'evaluating' || s.state === 'result');

    if (isLocked && s.detection && s.confidence > 0) {
        var cap = s.detection.charAt(0).toUpperCase() + s.detection.slice(1);
        dPanel.className = 'detect-display locked';
        dEmoji.textContent = EMOJIS[cap] || '\u270B';
        dLabel.textContent = cap + ' — locked in!';
        dConf.textContent = Math.round(s.confidence * 100) + '% confidence';
    } else if (isLocked) {
        dPanel.className = 'detect-display locked';
        dEmoji.textContent = '\u270B';
        dLabel.textContent = 'No gesture — locked';
        dConf.innerHTML = '&nbsp;';
    } else if (s.detection && s.confidence > 0) {
        var cap = s.detection.charAt(0).toUpperCase() + s.detection.slice(1);
        dPanel.className = 'detect-display active';
        dEmoji.textContent = EMOJIS[cap] || '\u270B';
        dLabel.textContent = cap;
        dConf.textContent = Math.round(s.confidence * 100) + '% confidence';
    } else {
        dPanel.className = 'detect-display';
        dEmoji.textContent = '\u270B';
        dLabel.textContent = 'Show your hand';
        dConf.innerHTML = '&nbsp;';
    }

    /* ── Arduino panel ── */
    if (s.state === 'countdown' && s.countdown != null) {
        emoji.textContent = s.countdown;
        emoji.className = 'move-emoji countdown-num';
        name.textContent = 'get ready';
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
            /* keep banner visible until next play */
        } else if (s.state === 'idle' && prevState === 'idle' && s.round === 0) {
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
function playRound() {
    document.getElementById('playBtn').disabled = true;
    hideBanner();
    ui.send_message('play'); // server rejects if busy; next 'state' push resyncs the button
}

function resetGame() {
    ui.send_message('reset'); // next 'state' push repaints scores/history/commentary
}

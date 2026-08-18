#!/usr/bin/env python3
"""
Rock-Paper-Scissors Game — Arduino UNO Q

Uses the video_object_detection brick for Edge Impulse inference.
The brick manages the camera and runs detection in its Docker container.
The web_ui brick serves the custom web UI and pushes state over WebSocket.
"""

import os
import sys
import time
import queue
import random
import threading

# ─── Non-blocking logging ────────────────────────────────────────────────
# Every detection stall we have hit traces back to a worker thread blocking
# while writing to stdout when the App Lab log pipe fills: a blocked write holds
# shared sys.stdout lock, which freezes every other thread — including the
# detector callback, which then stops servicing its WebSocket and detection
# dies (low CPU, app appears hung, restart doesn't help). So route ALL app
# logging through a bounded queue drained by one writer thread. Producer
# threads never block: if the queue is full (stdout wedged) we DROP the line
# rather than stall real work. Losing a log line is fine; stalling detection is
# not.
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

_log_queue = queue.Queue(maxsize=2000)


def log(msg):
    try:
        _log_queue.put_nowait(msg)
    except queue.Full:
        pass


def _log_writer():
    while True:
        msg = _log_queue.get()
        try:
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()
        except Exception:
            pass


threading.Thread(target=_log_writer, daemon=True).start()

# One confidence knob drives BOTH the brick's internal threshold and our filter
# so they never disagree. Override at runtime with the CONFIDENCE env var. The
# brick ignores anything below this before it ever calls us, so lowering it is
# the only way to see weaker detections in the logs.
CONFIDENCE_THRESHOLD = float(os.environ.get('CONFIDENCE', '0.4'))

# ─── Video Object Detection Brick ────────────────────────────────────────
_detector = None
try:
    from arduino.app_bricks.video_objectdetection import VideoObjectDetection
    _detector = VideoObjectDetection(confidence=CONFIDENCE_THRESHOLD, debounce_sec=0.0)
    log(f"[BRICK] VideoObjectDetection initialized (confidence={CONFIDENCE_THRESHOLD})")
except ImportError:
    log("[WARN] VideoObjectDetection brick not available — detection disabled")

# ─── LLM Brick (live play-by-play commentator) ───────────────────────────
_llm = None
LLM_PERSONA = (
    "You are an energetic live sports commentator narrating a Rock Paper "
    "Scissors duel between a Human and an Arduino robot. Reply with ONE short, "
    "punchy, exciting play-by-play line — like calling a football match. "
    "No emojis. Do not explain the rules. Do not use quotation marks."
)
try:
    from arduino.app_bricks.llm import LargeLanguageModel
    _llm = LargeLanguageModel(system_prompt=LLM_PERSONA, max_tokens=60, temperature=0.9)
    log("[BRICK] LargeLanguageModel initialized")
except ImportError:
    log("[WARN] LLM brick not available — commentary disabled")

# ─── Web UI Brick ────────────────────────────────────────────────────────
from arduino.app_bricks.web_ui import WebUI

ui = WebUI()

# ─── App Runner ──────────────────────────────────────────────────────────
_App = None
try:
    from arduino.app_utils import App as _App
except ImportError:
    try:
        from arduino.app import App as _App
    except ImportError:
        try:
            from arduino import App as _App
        except ImportError:
            pass

# ─── Configuration ───────────────────────────────────────────────────────
VALID_LABELS = {'rock', 'paper', 'scissors'}
COUNTDOWN_SECS = 3
RESULT_HOLD_SECS = 3
# Per-frame detection logging floods stdout; the App Lab log pipe then applies
# backpressure that can stall the detection callback thread. Off by default.
DEBUG_DETECTIONS = os.environ.get('DEBUG_DETECTIONS') == '1'

WINS = {'Rock': 'Scissors', 'Scissors': 'Paper', 'Paper': 'Rock'}


# ─── Game State ──────────────────────────────────────────────────────────
class GameState:
    """Thread-safe game state with scoring and round history."""

    def __init__(self):
        self._lock = threading.Lock()
        self.human_wins = 0
        self.arduino_wins = 0
        self.draws = 0
        self.round_number = 0
        self.state = 'idle'
        self.countdown = None
        self.arduino_move = None
        self.human_move = None
        self.winner = None
        self.detection = None
        self.confidence = 0.0
        self._detection_locked = False
        self.commentary = []
        self.commentating = False
        self.history = []

    def update_detection(self, label, confidence):
        changed = False
        with self._lock:
            if self._detection_locked:
                return
            prev = self.detection
            self.detection = label
            self.confidence = confidence
            changed = label != prev
        if changed:
            log(f"[DETECT] {label} ({confidence:.0%})")
            self.broadcast()

    def play_round(self):
        arduino_move = random.choice(['Rock', 'Paper', 'Scissors'])

        # Lock detection: snapshot the current gesture immediately
        with self._lock:
            self._detection_locked = True
            detected = self.detection
            conf = self.confidence
            self.state = 'countdown'
            self.arduino_move = arduino_move
            self.human_move = None
            self.winner = None

        log(f"[GAME] Locked detection: {detected} ({conf:.0%})" if detected else
              "[GAME] Locked detection: none")

        for tick in [3, 2, 1]:
            with self._lock:
                self.countdown = tick
            self.broadcast()
            time.sleep(1)

        with self._lock:
            self.state = 'evaluating'
            self.countdown = None
        self.broadcast()

        human_move = detected.capitalize() if detected and detected in VALID_LABELS else None

        if human_move and WINS.get(human_move):
            if human_move == arduino_move:
                winner = 'draw'
            elif WINS[human_move] == arduino_move:
                winner = 'human'
            else:
                winner = 'arduino'
        else:
            winner = 'no_detection'

        with self._lock:
            self.human_move = human_move
            self.winner = winner
            self.round_number += 1

            if winner == 'human':
                self.human_wins += 1
            elif winner == 'arduino':
                self.arduino_wins += 1
            elif winner == 'draw':
                self.draws += 1

            round_record = {
                'round': self.round_number,
                'humanMove': human_move,
                'arduinoMove': arduino_move,
                'winner': winner,
                'confidence': conf,
            }
            self.history.insert(0, round_record)
            self.state = 'result'
        self.broadcast()

        log(f"[GAME] Round {round_record['round']}: "
              f"Human={human_move or '?'} vs Arduino={arduino_move} -> {winner}")

        enqueue_milestone('result', winner=winner, human_move=human_move,
                          arduino_move=arduino_move)

        time.sleep(RESULT_HOLD_SECS)

        with self._lock:
            self.state = 'idle'
            self._detection_locked = False
        self.broadcast()

        return round_record

    def add_commentary(self, text):
        with self._lock:
            self.commentary.insert(0, text)
            del self.commentary[10:]
        self.broadcast()

    def set_commentating(self, value):
        with self._lock:
            self.commentating = value
        self.broadcast()

    def reset(self):
        with self._lock:
            self.human_wins = 0
            self.arduino_wins = 0
            self.draws = 0
            self.round_number = 0
            self.state = 'idle'
            self.countdown = None
            self.arduino_move = None
            self.human_move = None
            self.winner = None
            self._detection_locked = False
            self.commentary.clear()
            self.commentating = False
            self.history.clear()
        log("[GAME] Scores reset")
        self.broadcast()

    def broadcast(self):
        ui.send_message('state', self.to_dict())

    def to_dict(self):
        with self._lock:
            return {
                'humanWins': self.human_wins,
                'arduinoWins': self.arduino_wins,
                'draws': self.draws,
                'round': self.round_number,
                'state': self.state,
                'countdown': self.countdown,
                'arduinoMove': self.arduino_move,
                'humanMove': self.human_move,
                'winner': self.winner,
                'detection': self.detection,
                'confidence': self.confidence,
                'commentary': list(self.commentary),
                'commentating': self.commentating,
                'history': list(self.history),
            }


game = GameState()


# ─── Live Commentator ────────────────────────────────────────────────────
# One background worker turns game events into play-by-play lines. The local
# LLM is CPU-heavy and competes with the Edge Impulse detector for cores, which
# collapses detection throughput (seconds per frame). So we narrate ONLY the
# round result — one line per round, generated during the result hold when
# detection accuracy no longer matters — instead of every detection change or
# countdown milestone. This keeps live detection running at full speed.
_milestones = queue.Queue()


def enqueue_milestone(kind, **data):
    if not _llm:
        return
    _milestones.put({'kind': kind, **data})


def _prompt_for(event):
    if event['kind'] == 'result':
        verdict = {
            'human': 'the HUMAN wins the round',
            'arduino': 'the ARDUINO wins the round',
            'draw': "it's a DRAW",
            'no_detection': 'no valid move from the human — no contest',
        }.get(event['winner'], event['winner'])
        return (f"FINAL WHISTLE: {verdict}! Human played "
                f"{event.get('human_move') or '—'}, Arduino played {event['arduino_move']}. "
                f"Give the dramatic verdict.")
    return None


def commentator_worker():
    while True:
        event = _milestones.get()
        prompt = _prompt_for(event)
        if not prompt:
            continue
        game.set_commentating(True)
        try:
            text = _llm.chat(prompt).strip()
        except Exception as e:
            log(f"[LLM] commentary failed: {e}")
            game.set_commentating(False)
            continue
        game.set_commentating(False)
        if text:
            log(f"[LLM] {text}")
            game.add_commentary(text)


if _llm:
    threading.Thread(target=commentator_worker, daemon=True).start()


# ─── Brick Detection Callback ────────────────────────────────────────────
# The brick fires on_detect_all only when it has at least one detection — empty
# frames trigger no callback and the brick exposes no inference-time field. So
# we time the interval between callbacks ourselves as an effective inference
# cadence, and log a throttled heartbeat (once/sec) that proves inference is
# live without re-creating the per-frame print firehose that stalled stdout.
_infer_last_ts = None
_infer_last_log = 0.0
_infer_count = 0
_infer_intervals = []
_infer_lock = threading.Lock()


def handle_detections(detections):
    """Called by the video_object_detection brick with detection results.

    The brick may pass either:
      - {label: {"confidence": float}} (dict values)
      - {label: float}                 (plain float values)
      - {label: [ {"confidence": float, ...}, ... ]} (list of detail dicts)
    """
    if not detections:
        return

    if DEBUG_DETECTIONS:
        log(f"[BRICK-RAW] {detections}")

    best_label, best_conf = None, None
    try:
        valid = {}
        for k, v in detections.items():
            label = k.lower()
            if label not in VALID_LABELS:
                continue
            if isinstance(v, dict):
                conf = v.get("confidence")
            elif isinstance(v, list):
                conf = v[0].get("confidence") if v and isinstance(v[0], dict) else None
            else:
                conf = v
            if conf is not None and conf >= CONFIDENCE_THRESHOLD:
                valid[label] = conf
        if valid:
            best_label = max(valid, key=valid.get)
            best_conf = valid[best_label]
            game.update_detection(best_label, best_conf)
    except Exception as e:
        log(f"[BRICK] detection handler error: {e}")

    global _infer_last_ts, _infer_last_log, _infer_count
    now = time.perf_counter()
    with _infer_lock:
        _infer_count += 1
        if _infer_last_ts is not None:
            _infer_intervals.append((now - _infer_last_ts) * 1000.0)
            del _infer_intervals[100:]
        _infer_last_ts = now
        should_log = (now - _infer_last_log) >= 1.0
        if should_log:
            _infer_last_log = now
        count = _infer_count
        intervals = list(_infer_intervals)

    if should_log:
        det = f"{best_label} {best_conf:.0%}" if best_label else "no valid label"
        if intervals:
            last = intervals[-1]
            avg = sum(intervals) / len(intervals)
            rate = 1000.0 / avg if avg else 0.0
            log(f"[INFER] result #{count}  {det}  interval={last:.0f}ms  "
                  f"avg={avg:.0f}ms  ~{rate:.1f}/s")
        else:
            log(f"[INFER] result #{count}  {det} (first)")


if _detector:
    _detector.on_detect_all(handle_detections)


# ─── Web UI Actions ──────────────────────────────────────────────────────
def on_client_connect(sid):
    ui.send_message('state', game.to_dict(), room=sid)  # sync the new client immediately


def handle_play(sid, data):
    if game.to_dict()['state'] != 'idle':
        return
    threading.Thread(target=game.play_round, daemon=True).start()


def handle_reset(sid, data):
    game.reset()


ui.on_connect(on_client_connect)
ui.on_message('play', handle_play)
ui.on_message('reset', handle_reset)


# ─── Entry Point ─────────────────────────────────────────────────────────
if __name__ == '__main__':
    log('=' * 50)
    log('  Rock Paper Scissors — Arduino UNO Q')
    log('=' * 50)
    log(f'[MODE] Brick: {"yes" if _detector else "no"}')
    log(f'[MODE] LLM: {"yes" if _llm else "no"}')
    log(f'[MODE] App runner: {"yes" if _App else "no"}')

    if _App:
        _App.run()
    else:
        log('[WARN] No App runner — the WebUI brick needs App.run() to start its server')
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log('\n[EXIT] Shutting down')

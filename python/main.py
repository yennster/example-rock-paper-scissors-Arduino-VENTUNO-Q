#!/usr/bin/env python3
"""
Rock-Paper-Scissors Game — Arduino UNO Q

Uses the video_object_detection brick for Edge Impulse inference.
The brick manages the camera and runs detection in its Docker container.
The web_ui brick serves the custom web UI, relays the live camera feed as
MJPEG, and pushes state over WebSocket.
"""

import os
import sys
import time
import queue
import base64
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
# camera_preview=True makes the model runner push the frame it just classified
# back over its WebSocket. That is what feeds the live view in the UI: the
# brick's container owns the camera, so the app cannot open /dev/video itself
# without stealing frames from the detector.
_detector = None
try:
    from arduino.app_bricks.video_objectdetection import VideoObjectDetection
    try:
        _detector = VideoObjectDetection(confidence=CONFIDENCE_THRESHOLD,
                                         debounce_sec=0.0,
                                         camera_preview=True)
        log(f"[BRICK] VideoObjectDetection initialized "
            f"(confidence={CONFIDENCE_THRESHOLD}, camera preview on)")
    except TypeError:
        # Older brick builds have no camera_preview argument — keep the game
        # playable, just without the live feed.
        _detector = VideoObjectDetection(confidence=CONFIDENCE_THRESHOLD, debounce_sec=0.0)
        log(f"[BRICK] VideoObjectDetection initialized (confidence={CONFIDENCE_THRESHOLD}, "
            f"no camera preview support)")
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

# Continuous play: rounds run back to back on their own. The gesture is
# sampled at the instant the countdown hits zero ("shoot"), so nothing has to
# be locked in up front.
COUNTDOWN_SECS = int(os.environ.get('COUNTDOWN_SECS', '3'))
SHOOT_HOLD_SECS = 0.7
RESULT_HOLD_SECS = float(os.environ.get('RESULT_HOLD_SECS', '3.5'))

# Detections stop arriving entirely when the frame is empty, so the overlay
# needs its own staleness timer to clear the boxes.
DETECTION_TTL_SECS = 0.6

# The local LLM is CPU-heavy and competes with the detector for cores. With
# rounds now looping non-stop, rate-limit commentary so detection keeps up.
COMMENTARY_MIN_INTERVAL = float(os.environ.get('COMMENTARY_MIN_INTERVAL', '8'))

# Per-frame detection logging floods stdout; the App Lab log pipe then applies
# backpressure that can stall the detection callback thread. Off by default.
DEBUG_DETECTIONS = os.environ.get('DEBUG_DETECTIONS') == '1'

WINS = {'Rock': 'Scissors', 'Scissors': 'Paper', 'Paper': 'Rock'}


# ─── Live Camera Relay ───────────────────────────────────────────────────
# The model runner sends back the exact frame it classified, base64-encoded,
# on every camera snapshot. We keep only the newest one and re-serve it as an
# MJPEG stream so the browser can show a live feed with a single <img> tag.
#
# Why re-serve the runner's frame instead of reading the camera directly:
# the brick's container holds the camera and Camera.capture() hands each frame
# to exactly one caller, so a second reader would halve the detector's frame
# rate. Relaying also guarantees the overlay lines up — the brick runs the
# runner with --preview-original-resolution, which means the bounding boxes
# are already scaled to this very frame's pixel coordinates.
_frame_cv = threading.Condition()
_frame_jpeg = None
_frame_seq = 0
_pump_live = False


def publish_frame(jpeg):
    """Hand a new JPEG frame to every connected MJPEG viewer."""
    global _frame_jpeg, _frame_seq
    if not jpeg:
        return
    with _frame_cv:
        _frame_jpeg = jpeg
        _frame_seq += 1
        _frame_cv.notify_all()


def preview_pump():
    """Decode the brick's newest preview frame into the MJPEG buffer.

    The brick only hands frames to the detection callback when something was
    actually detected, which would freeze the feed whenever the frame is
    empty. Its internal buffer is refreshed on every camera snapshot, so poll
    that instead and fall back to callback frames if it is unavailable.
    """
    global _pump_live
    last = None
    misses = 0
    while True:
        raw = getattr(_detector, '_last_camera_frame', None)
        if isinstance(raw, str) and raw and raw is not last:
            last = raw
            try:
                publish_frame(base64.b64decode(raw.split(',', 1)[-1]))
                if not _pump_live:
                    _pump_live = True
                    log('[CAMERA] Live preview stream active')
            except Exception as e:
                log(f'[CAMERA] Failed to decode preview frame: {e}')
        elif not _pump_live:
            misses += 1
            if misses == 200:  # ~10s with nothing: say so once, then keep trying
                log('[CAMERA] No preview frames yet from the model runner')
        time.sleep(0.05)


def mjpeg_frames():
    """Yield multipart MJPEG parts, one per new frame, blocking in between."""
    seq = -1
    while True:
        with _frame_cv:
            if _frame_seq == seq:
                _frame_cv.wait(timeout=2.0)
            if _frame_seq == seq:
                continue  # no new frame yet — keep the connection open
            seq = _frame_seq
            frame = _frame_jpeg
        if frame:
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


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
        self.auto = False
        self._detection_locked = False
        self.commentary = []
        self.commentating = False
        self.history = []
        # Set to cut a round short when the player pauses or resets.
        self._abort = threading.Event()

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

    def clear_detection(self):
        """Forget the last gesture once the camera has gone quiet."""
        changed = False
        with self._lock:
            if self._detection_locked or self.detection is None:
                return
            self.detection = None
            self.confidence = 0.0
            changed = True
        if changed:
            self.broadcast()

    # ── Continuous play control ──────────────────────────────────────────
    def is_auto(self):
        with self._lock:
            return self.auto

    def start_auto(self):
        # Clear the abort flag first: the round loop can pick up `auto` the
        # instant it flips, and a stale abort would kill the round on sight.
        self._abort.clear()
        with self._lock:
            if self.auto:
                return False
            self.auto = True
        _play_gate.set()
        log('[GAME] Continuous play started')
        self.broadcast()
        return True

    def stop_auto(self):
        with self._lock:
            was = self.auto
            self.auto = False
        self._abort.set()
        if was:
            log('[GAME] Continuous play paused')
        self.broadcast()
        return was

    def _wait(self, seconds):
        """Sleep unless the round is aborted. Returns True when aborted."""
        return self._abort.wait(seconds)

    def play_round(self):
        """Run one round: countdown, shoot, evaluate, hold the result.

        The gesture is read at the moment the countdown hits zero rather than
        being locked in beforehand, so the player can keep moving right up to
        the last instant.
        """
        arduino_move = random.choice(['Rock', 'Paper', 'Scissors'])

        with self._lock:
            self.state = 'countdown'
            self.arduino_move = None  # stays hidden until the reveal
            self.human_move = None
            self.winner = None
            self._detection_locked = False
        self.broadcast()

        for tick in range(COUNTDOWN_SECS, 0, -1):
            with self._lock:
                self.countdown = tick
            self.broadcast()
            if self._wait(1.0):
                return self._abandon()

        # ── Shoot: snapshot whatever the camera sees right now ──
        with self._lock:
            self.state = 'shoot'
            self.countdown = 0
            self._detection_locked = True
            detected = self.detection
            conf = self.confidence
            self.arduino_move = arduino_move
        self.broadcast()

        log(f"[GAME] Shoot! Captured: {detected} ({conf:.0%})" if detected else
            "[GAME] Shoot! Captured: no gesture")

        if self._wait(SHOOT_HOLD_SECS):
            return self._abandon()

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
            self.countdown = None
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
            del self.history[50:]
            self.state = 'result'
        self.broadcast()

        log(f"[GAME] Round {round_record['round']}: "
              f"Human={human_move or '?'} vs Arduino={arduino_move} -> {winner}")

        enqueue_milestone('result', winner=winner, human_move=human_move,
                          arduino_move=arduino_move)

        aborted = self._wait(RESULT_HOLD_SECS)

        with self._lock:
            self._detection_locked = False
            if not self.auto:
                self.state = 'idle'
        self.broadcast()

        return not aborted

    def _abandon(self):
        """Roll the round back to idle after a pause or reset."""
        with self._lock:
            self.state = 'idle'
            self.countdown = None
            self.arduino_move = None
            self.human_move = None
            self.winner = None
            self._detection_locked = False
        self.broadcast()
        return False

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
            self.auto = False
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
        self._abort.set()
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
                'auto': self.auto,
                'locked': self._detection_locked,
                'cameraAvailable': _detector is not None,
                'commentary': list(self.commentary),
                'commentating': self.commentating,
                'history': list(self.history),
            }


game = GameState()


# ─── Continuous Round Loop ───────────────────────────────────────────────
# One worker drives rounds back to back while auto play is on, so the player
# never has to press anything between rounds.
_play_gate = threading.Event()


def round_loop():
    while True:
        if not game.is_auto():
            _play_gate.wait(timeout=0.5)
            _play_gate.clear()
            continue
        if not game.play_round():
            _play_gate.clear()


threading.Thread(target=round_loop, daemon=True).start()


# ─── Live Commentator ────────────────────────────────────────────────────
# One background worker turns game events into play-by-play lines. The local
# LLM is CPU-heavy and competes with the Edge Impulse detector for cores, which
# collapses detection throughput (seconds per frame). So we narrate ONLY the
# round result — one line per round, generated during the result hold when
# detection accuracy no longer matters — instead of every detection change or
# countdown milestone. This keeps live detection running at full speed.
_milestones = queue.Queue()
_last_commentary_ts = 0.0


def enqueue_milestone(kind, **data):
    """Queue a commentary event, dropping it when the LLM is still catching up.

    Rounds now run continuously, so an unthrottled queue would keep the LLM
    busy permanently and starve the detector of CPU.
    """
    if not _llm:
        return
    if not _milestones.empty():
        return  # a line is already pending — skip rather than pile up
    if time.monotonic() - _last_commentary_ts < COMMENTARY_MIN_INTERVAL:
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
    global _last_commentary_ts
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
            _last_commentary_ts = time.monotonic()
            continue
        game.set_commentating(False)
        _last_commentary_ts = time.monotonic()
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

# Latest boxes pushed to the browser, plus when the last detection arrived, so
# a watchdog can clear the overlay once the frame goes empty (the brick fires
# no callback at all in that case).
_boxes_lock = threading.Lock()
_detect_last_ts = 0.0
_overlay_live = False


def publish_boxes(boxes):
    """Push the current bounding boxes to every browser on their own channel.

    Kept separate from the game-state broadcast: boxes change on every frame
    while the rest of the state rarely does, and the overlay should not drag
    the full history/commentary payload along ~10 times a second.
    """
    global _detect_last_ts, _overlay_live
    with _boxes_lock:
        _detect_last_ts = time.monotonic()
        _overlay_live = True
    try:
        ui.send_message('detections', {'boxes': boxes})
    except Exception as e:
        log(f"[BRICK] failed to publish boxes: {e}")


def boxes_watchdog():
    """Clear the overlay and the gesture once detections stop arriving."""
    global _overlay_live
    while True:
        time.sleep(DETECTION_TTL_SECS / 2.0)
        with _boxes_lock:
            stale = _overlay_live and (time.monotonic() - _detect_last_ts) > DETECTION_TTL_SECS
            if stale:
                _overlay_live = False
        if stale:
            try:
                ui.send_message('detections', {'boxes': []})
            except Exception:
                pass
            game.clear_detection()


def _extract(value):
    """Normalize one brick detection value to (confidence, bounding box).

    The brick may pass either:
      - {label: {"confidence": float, "bounding_box_xyxy": (...)}} (dict)
      - {label: float}                                            (plain float)
      - {label: [ {"confidence": float, ...}, ... ]}              (list of dicts)
    """
    if isinstance(value, dict):
        return value.get('confidence'), value.get('bounding_box_xyxy')
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            return value[0].get('confidence'), value[0].get('bounding_box_xyxy')
        return None, None
    return value, None


def _iter_details(value):
    """Yield every (confidence, bounding box) pair carried by a brick value."""
    if isinstance(value, list):
        for item in value:
            yield _extract(item)
    else:
        yield _extract(value)


def handle_detections(detections, frame=None):
    """Called by the video_object_detection brick with detection results.

    `frame` is the raw JPEG the model just classified (camera_preview=True).
    Bounding boxes are expressed in that frame's pixel coordinates, so the UI
    can draw them straight onto the relayed video with no rescaling.
    """
    if frame and not _pump_live:
        # Fallback path: only used if the brick's preview buffer is unreadable.
        publish_frame(frame)

    if not detections:
        return

    if DEBUG_DETECTIONS:
        log(f"[BRICK-RAW] {detections}")

    best_label, best_conf = None, None
    try:
        valid = {}
        boxes = []
        for k, v in detections.items():
            label = k.lower()
            for conf, bbox in _iter_details(v):
                if conf is None or conf < CONFIDENCE_THRESHOLD:
                    continue
                if bbox and len(bbox) == 4:
                    boxes.append({
                        'label': label,
                        'confidence': round(float(conf), 4),
                        'box': [int(round(float(n))) for n in bbox],
                    })
                if label in VALID_LABELS and conf > valid.get(label, 0.0):
                    valid[label] = conf

        publish_boxes(boxes)

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
    threading.Thread(target=preview_pump, daemon=True).start()
    threading.Thread(target=boxes_watchdog, daemon=True).start()


# ─── Web UI Actions ──────────────────────────────────────────────────────
def on_client_connect(sid):
    ui.send_message('state', game.to_dict(), room=sid)  # sync the new client immediately


def handle_start(sid, data):
    game.start_auto()


def handle_pause(sid, data):
    game.stop_auto()


def handle_reset(sid, data):
    game.reset()


ui.on_connect(on_client_connect)
ui.on_message('start', handle_start)
ui.on_message('pause', handle_pause)
ui.on_message('reset', handle_reset)


# ─── Live Camera Endpoint ────────────────────────────────────────────────
# Served as MJPEG so the page can show it with a plain <img src="/camera">.
if _detector:
    def camera_stream():
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            mjpeg_frames(),
            media_type='multipart/x-mixed-replace; boundary=frame',
            headers={'Cache-Control': 'no-store'},
        )

    ui.expose_api('GET', '/camera', camera_stream)


# ─── Entry Point ─────────────────────────────────────────────────────────
if __name__ == '__main__':
    log('=' * 50)
    log('  Rock Paper Scissors TTC 2026 — Arduino UNO Q')
    log('=' * 50)
    log(f'[MODE] Brick: {"yes" if _detector else "no"}')
    log(f'[MODE] LLM: {"yes" if _llm else "no"}')
    log(f'[MODE] App runner: {"yes" if _App else "no"}')
    log(f'[MODE] Live camera feed: {"/camera" if _detector else "unavailable"}')

    if _App:
        _App.run()
    else:
        log('[WARN] No App runner — the WebUI brick needs App.run() to start its server')
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log('\n[EXIT] Shutting down')

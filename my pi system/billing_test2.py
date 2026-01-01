#!/usr/bin/env python
# -*- coding: utf-8 -*-

import cv2
import os
import sys
import getopt
import signal
import time
from collections import deque

from edge_impulse_linux.image import ImageImpulseRunner
from picamera2 import Picamera2
import numpy as np

import RPi.GPIO as GPIO
from hx711 import HX711

import requests
import json
from requests.structures import CaseInsensitiveDict

# -----------------------------
# CONFIG (tune if needed)
# -----------------------------
POST_URL = "https://lionfish-app-oy7gr.ondigitalocean.app/product"

DETECTION_THRESHOLD = 0.90    # keep high to reduce false positives
GAP_FINALIZE_MS = 700         # finalize if we lose confident detections for this long
STABLE_MS = 1200              # time the same item must persist before we can consider it stable
STABLE_WEIGHTS = 8            # weight samples to assess stability
STABLE_DELTA_G = 3            # max weight jitter (g) across samples to call stable

# Scale
HX_DOUT = 5
HX_SCK = 6
SCALE_RATIO = 458.7

# Camera
FRAME_INTERVAL_MS = 100       # ~10 FPS pacing for the main loop
SHOW_CAMERA = False           # set True to see the preview window

# -----------------------------
# GLOBALS
# -----------------------------
picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"format": 'RGB888', "size": (640, 480)}))
picam2.start()

runner = None

# scale / weight
hx = None
calibrated = False

# posting / transaction
id_product = 1

# rolling state for “previous item” logic
list_label = []
list_weight = []
count = 0
taken = 0

# finalize triggers
last_detect_ms = 0

# stability for current item (weight only)
active_started_ms = 0
active_weights = deque(maxlen=STABLE_WEIGHTS)

# -----------------------------
# UTILS / SIGNALS
# -----------------------------
def now_ms():
    return int(round(time.time() * 1000))

def now():
    return now_ms()

def sigint_handler(sig, frame):
    print('Interrupted')
    try:
        if runner:
            runner.stop()
    except Exception:
        pass
    try:
        if hx:
            GPIO.cleanup()
    except Exception:
        pass
    try:
        if picam2:
            picam2.stop()
    except Exception:
        pass
    cv2.destroyAllWindows()
    sys.exit(0)

signal.signal(signal.SIGINT, sigint_handler)

def help():
    print('Usage:\n  python billing_test2.py <path_to_model.eim>')

# -----------------------------
# SCALE / WEIGHT
# -----------------------------
def ensure_scale():
    """Initialize HX711 once."""
    global calibrated, hx
    if calibrated:
        return
    print('Scale: calibration starts…')
    try:
        GPIO.setmode(GPIO.BCM)
        hx = HX711(dout_pin=HX_DOUT, pd_sck_pin=HX_SCK)
        err = hx.zero()
        if err:
            raise ValueError('Tare is unsuccessful.')
        hx.set_scale_ratio(SCALE_RATIO)
        calibrated = True
        print('Scale: calibration done.')
    except Exception as e:
        print(f'Calibration failed: {e}')
        GPIO.cleanup()
        sys.exit(1)

def read_weight():
    """Read current weight (g), with light debounce."""
    ensure_scale()
    try:
        time.sleep(0.08)
        w = int(hx.get_weight_mean(20))
        print(f'Weight: {w} g')
        return w
    except Exception as e:
        print(f'Weight read failed: {e}')
        return 0

# -----------------------------
# SERVER POST
# -----------------------------
def post_item(label, price, payable_total, units_count):
    """POST one item to your server using the exact schema your UI expects."""
    global id_product
    headers = CaseInsensitiveDict({"Content-Type": "application/json"})
    payload = {
        "id": str(id_product),          # string id => your server routes match cleanly
        "name": label,
        "price": float(price),
        "unit": "units",                # UI reads `unit` (singular)
        "units": "units",               # harmless extra
        "taken": int(units_count),
        "payable": float(payable_total),
    }
    try:
        r = requests.post(POST_URL, headers=headers, data=json.dumps(payload), timeout=5)
        print("POST /product ->", r.status_code, payload)
    except Exception as e:
        print("POST failed:", e)
    id_product += 1

# -----------------------------
# PRICING
# -----------------------------
def price_and_units_from(label, grams):
    """Return (price_per_unit, units) or (None, None) if label is unknown."""
    if label == 'chocolate':
        pack_w, price = 17, 50
    elif label == 'eno':
        pack_w, price = 6, 70
    elif label == 'mentos packet':
        pack_w, price = 5, 20
    elif label == 'nescafe packet':
        pack_w, price = 2, 25
    elif label == 'stix':
        pack_w, price = 20, 40
    elif label == 'toffee':
        pack_w, price = 2, 10
    else:
        return None, None
    units = max(1, round(float(grams) / float(pack_w)))
    return price, units

def finalize_and_post(label, grams):
    price, units = price_and_units_from(label, grams)
    if price is None:
        print(f"Unknown label '{label}', skipping.")
        return
    total = float(price) * int(units)
    print(f"Finalize: {label} ~{grams}g -> units={units}, total={total}")
    post_item(label, price, round(total, 2), units)

# -----------------------------
# ROLLING / FINALIZE LOGIC
# -----------------------------
def push_observation(label, grams):
    """Keep label/weight history. On label change, finalize the previous item."""
    global list_label, list_weight, count, taken, active_started_ms, active_weights

    # weight history for “previous item” path
    list_label.append(label)
    list_weight.append(grams if grams > 2 else None)
    count += 1

    # track active item weight range (for stability)
    if grams is not None:
        active_weights.append(grams)
    if count == 1:
        active_started_ms = now_ms()

    # simple “taken” counter on rising weight (optional)
    if len(list_weight) >= 2:
        w_prev = list_weight[-2]
        w_curr = list_weight[-1]
        if isinstance(w_prev, (int, float)) and isinstance(w_curr, (int, float)) and (w_curr > w_prev):
            taken += 1

    print(f'Obs count: {count}')

    # finalize previous item immediately when label changes
    if count > 1 and list_label[-1] != list_label[-2]:
        prev_label = list_label[-2]
        # find last valid weight for previous item
        prev_weight = 0
        for w in reversed(list_weight[:-1]):
            if isinstance(w, (int, float)):
                prev_weight = w
                break
        print(f"Label changed: finalize '{prev_label}' at ~{prev_weight} g")
        finalize_and_post(prev_label, prev_weight)
        # reset rollup for next item
        reset_rollup()

def reset_rollup():
    """Reset rolling buffers for the next item."""
    global list_label, list_weight, count, taken, active_started_ms, active_weights
    list_label = []
    list_weight = []
    count = 0
    taken = 0
    active_started_ms = 0
    active_weights.clear()

def active_is_stable():
    """Decide if the current item (same label) has stabilized by time & weight jitter."""
    if count == 0:
        return False
    dur = now_ms() - active_started_ms
    if dur < STABLE_MS:
        return False
    valid = [w for w in active_weights if isinstance(w, (int, float))]
    if len(valid) < max(3, STABLE_WEIGHTS // 2):
        return False
    vmin, vmax = min(valid), max(valid)
    stable = (vmax - vmin) <= STABLE_DELTA_G
    print(f"Active stability: dur={dur}ms, range={vmax - vmin}g -> {'OK' if stable else 'no'}")
    return stable

def finalize_if_gap_elapsed():
    """Finalize current item if we lost confident detections for a short gap."""
    if count == 0:
        return
    # use the last valid numeric weight as final weight
    final_w = 0
    for w in reversed(list_weight):
        if isinstance(w, (int, float)):
            final_w = w
            break
    label = list_label[-1]
    print(f"(gap) Finalizing '{label}' at ~{final_w} g")
    finalize_and_post(label, final_w)
    reset_rollup()

# -----------------------------
# MAIN
# -----------------------------
def main(argv):
    global runner, last_detect_ms

    ensure_scale()

    try:
        opts, args = getopt.getopt(argv, "h", ["help"])
    except getopt.GetoptError:
        help()
        sys.exit(2)

    for opt, arg in opts:
        if opt in ('-h', '--help'):
            help()
            sys.exit()

    if len(args) == 0:
        help()
        sys.exit(2)

    model = args[0]
    dir_path = os.path.dirname(os.path.realpath(__file__))
    modelfile = os.path.join(dir_path, model)
    print(f'MODEL: {modelfile}')

    try:
        runner = ImageImpulseRunner(modelfile)
        model_info = runner.init()
        print(f'Loaded runner for "{model_info["project"]["owner"]} / {model_info["project"]["name"]}"')
        print("Starting video stream and classification…")

        next_frame = now_ms()
        last_debug = 0

        while True:
            # fps pacing
            if next_frame > now_ms():
                time.sleep((next_frame - now_ms()) / 1000.0)

            frame = picam2.capture_array()
            if SHOW_CAMERA:
                cv2.imshow("PiCam", frame)

            # EI features + inference
            features, _ = runner.get_features_from_image(frame)
            res = runner.classify(features)

            result = res.get("result", {})
            t_ms = res.get("timing", {}).get("dsp", 0) + res.get("timing", {}).get("classification", 0)

            saw_strong = False

            # ----- Classification path -----
            if "classification" in result:
                cls = result["classification"] or {}
                if cls:
                    best_label = max(cls, key=lambda k: cls[k])
                    score = float(cls[best_label])

                    if now_ms() - last_debug > 500:
                        print(f"Top: {best_label} {score:.2f} ({t_ms} ms)")
                        last_debug = now_ms()

                    if score >= DETECTION_THRESHOLD:
                        saw_strong = True
                        last_detect_ms = now_ms()
                        w = read_weight()
                        push_observation(best_label, w)

                        # also finalize when same item stabilizes (no need to wait for a new label)
                        if active_is_stable():
                            # finalize current item by last valid weight
                            finalize_if_gap_elapsed()  # reuses the “pick last valid weight + reset” logic

            # ----- Object detection path -----
            elif "bounding_boxes" in result:
                raw = result.get("bounding_boxes", []) or []
                # keep boxes over threshold
                boxes = [b for b in raw if float(b.get("value", 0.0)) >= DETECTION_THRESHOLD]

                if now_ms() - last_debug > 500:
                    dbg = ", ".join([f"{b.get('label','?')} {float(b.get('value',0)):.2f}" for b in raw[:3]])
                    print(f"OD top: {dbg} ({t_ms} ms)")
                    last_debug = now_ms()

                if boxes:
                    saw_strong = True
                    top = max(boxes, key=lambda b: float(b.get("value", 0.0)))
                    best_label = top.get("label", "unknown")
                    score = float(top.get("value", 0.0))
                    last_detect_ms = now_ms()
                    w = read_weight()
                    push_observation(best_label, w)

                    if active_is_stable():
                        finalize_if_gap_elapsed()

            # ----- Finalize by disappear gap (fixes first-item delay) -----
            if not saw_strong and count > 0 and (now_ms() - last_detect_ms) >= GAP_FINALIZE_MS:
                finalize_if_gap_elapsed()

            if SHOW_CAMERA:
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

            next_frame = now_ms() + FRAME_INTERVAL_MS

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        print("Cleaning up resources…")
        try:
            if runner:
                runner.stop()
        except Exception:
            pass
        try:
            if picam2:
                picam2.stop()
        except Exception:
            pass
        try:
            if hx:
                GPIO.cleanup()
        except Exception:
            pass
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main(sys.argv[1:])

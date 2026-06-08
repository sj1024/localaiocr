import json
import os
import time
import threading
import cv2
from pathlib import Path
from flask import Flask, Response, render_template, request, jsonify

from picamera2 import Picamera2
from gemma_reader import GemmaReader
from collections import deque
from roi import get_roi, save_roi
from output import CSVWriter

app = Flask(__name__)

CONFIG_PATH = Path(__file__).parent / "config.json"

frame_lock = threading.Lock()
crop_lock = threading.Lock()
current_frame = None
current_crop = None
current_color_crop = None
recent_rois = deque(maxlen=6)
last_roi_append = 0.0
latest_results = []
roi = None
ocr = None
writer = None
capture_interval = 5
rotation_angle = 0
last_ocr_time = 0


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def init():
    global roi, ocr, writer, capture_interval, rotation_angle
    config = load_config()
    capture_interval = config["capture_interval"]
    rotation_angle = config.get("rotation", 0)
    roi = get_roi()
    ocr = GemmaReader()
    writer = CSVWriter(config["output_csv"])


def camera_thread():
    global current_frame, current_crop, roi, last_ocr_time, latest_results
    config = load_config()
    cam = Picamera2(config["camera_index"])
    cam_config = cam.create_video_configuration(main={"size": (2304, 1296)})
    cam.configure(cam_config)
    cam.start()
    ae_enable = config.get("ae_enable", True)
    controls = {
        "AeEnable": ae_enable,
        "AwbEnable": config.get("awb_enable", True),
    }
    if not ae_enable:
        controls["ExposureTime"] = config.get("exposure_time", 50000)
        controls["AnalogueGain"] = config.get("analogue_gain", 4.0)
    af_mode = config.get("af_mode", 2)
    if af_mode in (0, 1, 2):
        controls["AfMode"] = af_mode
        if af_mode == 0:
            controls["LensPosition"] = config.get("lens_position", 0.0)
    cam.set_controls(controls)
    time.sleep(1.0)

    try:
        while True:
            frame = cam.capture_array()
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            with frame_lock:
                current_frame = frame.copy()

            if roi:
                x, y, w, h = roi
                crop = frame[y : y + h, x : x + w]
                rot = rotation_angle
                if rot == 90:
                    crop = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
                elif rot == 180:
                    crop = cv2.rotate(crop, cv2.ROTATE_180)
                elif rot == 270:
                    crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)
                global last_roi_append
                if time.time() - last_roi_append >= 0.4:
                    last_roi_append = time.time()
                    recent_rois.append(crop.copy())
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                ret, jpeg = cv2.imencode(".jpg", gray)
                if ret:
                    with crop_lock:
                        current_crop = jpeg.tobytes()
                ret_c, jpeg_c = cv2.imencode(".jpg", crop)
                if ret_c:
                    with crop_lock:
                        global current_color_crop
                        current_color_crop = jpeg_c.tobytes()

            now = time.time()
            if roi and now - last_ocr_time >= capture_interval:
                last_ocr_time = now
                x, y, w, h = roi
                roi_img = frame[y : y + h, x : x + w]
                rot = rotation_angle
                if rot == 90:
                    roi_img = cv2.rotate(roi_img, cv2.ROTATE_90_CLOCKWISE)
                elif rot == 180:
                    roi_img = cv2.rotate(roi_img, cv2.ROTATE_180)
                elif rot == 270:
                    roi_img = cv2.rotate(roi_img, cv2.ROTATE_90_COUNTERCLOCKWISE)
                def _do_ocr(img, ts):
                    global latest_results
                    s, info = ocr.read_frame(img)
                    nums = [s] if s else []
                    if s:
                        ch = info.get('charging'); di = info.get('discharging')
                        writer.write(ts, s, ch, di)
                        try:
                            os.makedirs('dataset/labeled', exist_ok=True)
                            tss = time.strftime('%Y%m%d_%H%M%S', time.localtime(ts))
                            cy = 'Y' if ch else 'N'; dy = 'Y' if di else 'N'
                            cv2.imwrite('dataset/labeled/%s_C%s_D%s__%s.jpg' % (s, cy, dy, tss), img)
                        except Exception as e:
                            print('labeled save err:', e, flush=True)
                    latest_results.append((ts, nums))
                    if len(latest_results) > 100:
                        latest_results = latest_results[-100:]
                threading.Thread(target=_do_ocr, args=(roi_img.copy(), now), daemon=True).start()

            time.sleep(0.033)
    except Exception as e:
        print(f"Camera thread error: {e}")
    finally:
        cam.stop()
        cam.close()


def generate_frames():
    while True:
        with frame_lock:
            if current_frame is None:
                time.sleep(0.1)
                continue
            frame = current_frame.copy()

        if roi:
            x, y, w, h = roi
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        H, W = frame.shape[:2]
        if W > 640:
            frame = cv2.resize(frame, (640, int(H * 640 / W)), interpolation=cv2.INTER_AREA)
        ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
        if ret:
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" +
                   jpeg.tobytes() + b"\r\n")
        time.sleep(0.033)


def generate_crop_frames():
    while True:
        with crop_lock:
            if current_crop is None:
                time.sleep(0.1)
                continue
            crop_bytes = current_crop

        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" +
               crop_bytes + b"\r\n")
        time.sleep(0.033)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    return Response(generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/crop_feed")
def crop_feed():
    return Response(generate_crop_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/roi", methods=["GET", "POST"])
def api_roi():
    global roi
    if request.method == "POST":
        data = request.json
        x, y, w, h = int(data["x"]), int(data["y"]), int(data["w"]), int(data["h"])
        if w <= 0 or h <= 0:
            roi = None
            save_roi(None)
            return jsonify({"status": "ok", "roi": None})
        roi = (x, y, w, h)
        save_roi([x, y, w, h])
        return jsonify({"status": "ok", "roi": list(roi)})
    fw = fh = None
    with frame_lock:
        if current_frame is not None:
            fh, fw = current_frame.shape[:2]
    return jsonify({"roi": list(roi) if roi else None, "frame": [fw, fh]})


@app.route("/api/results")
def api_results():
    ts_results = []
    for ts, nums in latest_results:
        ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        ts_results.append({"time": ts_str, "numbers": nums})
    return jsonify({"results": ts_results})


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    global capture_interval, rotation_angle
    if request.method == "POST":
        data = request.json
        config = load_config()
        for key in ["capture_interval", "ae_enable", "exposure_time", "analogue_gain", "output_csv", "af_mode", "lens_position", "awb_enable"]:
            if key in data:
                config[key] = data[key]
                if key == "capture_interval":
                    capture_interval = float(data[key])
                elif key == "output_csv":
                    global writer
                    writer = CSVWriter(data[key])
        if "rotation" in data:
            new_rot = int(data["rotation"])
            if new_rot not in (0, 90, 180, 270):
                return jsonify({"status": "error", "message": "rotation must be 0, 90, 180, or 270"}), 400
            rotation_angle = new_rot
            config["rotation"] = new_rot
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=4)
        return jsonify({"status": "ok", "note": "ae_enable/exposure_time/analogue_gain/af changes apply after server restart"})
    return jsonify(load_config())


@app.route("/api/crop_image")
def api_crop_image():
    with crop_lock:
        if current_crop is None:
            return jsonify({"status": "error", "message": "no crop available"}), 404
        data = current_crop
    from flask import send_file
    import io
    return send_file(io.BytesIO(data), mimetype="image/jpeg",
                     as_attachment=True,
                     download_name=f"crop_{time.strftime('%H%M%S')}.jpg")


@app.route("/api/color_crop")
def api_color_crop():
    global current_color_crop
    with crop_lock:
        if current_color_crop is None:
            return jsonify({"status": "error", "message": "no color crop"}), 404
        data = current_color_crop
    from flask import send_file
    import io
    return send_file(io.BytesIO(data), mimetype="image/jpeg",
                     as_attachment=True,
                     download_name=f"color_crop_{time.strftime('%H%M%S')}.jpg")


if __name__ == "__main__":
    init()
    t = threading.Thread(target=camera_thread, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=8889, debug=False, threaded=True)

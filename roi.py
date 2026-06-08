import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def save_roi(roi):
    config = load_config()
    config["roi"] = roi
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)


def get_roi():
    config = load_config()
    roi = config.get("roi")
    if roi is not None:
        x, y, w, h = roi
        return (x, y, w, h)
    return None


def select_roi(frame):
    import cv2

    preview_path = str(CONFIG_PATH.parent / "preview.jpg")
    cv2.imwrite(preview_path, frame)
    print(f"미리보기 이미지 저장됨: {preview_path}")
    print(f"이미지 해상도: {frame.shape[1]}x{frame.shape[0]}")
    print()
    print("ROI(관심 영역)를 설정하세요. 형식: x y width height")
    print("예: 100 50 400 200  (좌측상단 x=100, y=50, 너비=400, 높이=200)")
    print()

    while True:
        try:
            inp = input("ROI 좌표 입력 > ").strip()
            parts = inp.split()
            if len(parts) != 4:
                print("4개의 숫자를 입력하세요 (x y w h)")
                continue
            x, y, w, h = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            if x < 0 or y < 0 or w <= 0 or h <= 0:
                print("x, y는 0 이상, w, h는 1 이상이어야 합니다.")
                continue
            if x + w > frame.shape[1] or y + h > frame.shape[0]:
                print(f"ROI가 이미지 범위를 벗어납니다. 이미지 크기: {frame.shape[1]}x{frame.shape[0]}")
                continue
            break
        except ValueError:
            print("유효한 정수를 입력하세요.")
        except (EOFError, KeyboardInterrupt):
            return None

    save_roi([x, y, w, h])
    print(f"ROI 저장됨: x={x}, y={y}, w={w}, h={h}")
    return (x, y, w, h)

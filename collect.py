"""
데이터 수집기: webserver의 color_crop을 주기적으로 저장 (학습용).
크롭은 용량 허용하는 한 무제한 누적 — 디스크 여유가 MIN_FREE_GB 미만이면
오래된 것부터 삭제해 안전 마진 유지.
"""
import time, urllib.request, os, glob, shutil
from datetime import datetime

OUT = "/home/padmd/videoprocessing/dataset/raw"
URL = "http://localhost:8889/api/color_crop"
INTERVAL = 30          # 초
MIN_FREE_GB = 2.0      # 디스크 여유 안전 마진
CLEAN_EVERY = 20       # N회 저장마다 디스크 점검

os.makedirs(OUT, exist_ok=True)


def cleanup_if_low():
    """디스크 여유가 부족하면 오래된 크롭부터 삭제"""
    free_gb = shutil.disk_usage(OUT).free / 1e9
    if free_gb >= MIN_FREE_GB:
        return
    files = sorted(glob.glob(os.path.join(OUT, "crop_*.jpg")))
    # 여유 확보될 때까지 오래된 것부터 10%씩 삭제
    while files and shutil.disk_usage(OUT).free / 1e9 < MIN_FREE_GB:
        batch = files[:max(1, len(files) // 10)]
        for f in batch:
            try:
                os.remove(f); files.remove(f)
            except OSError:
                pass
        print(f"디스크 정리: {len(batch)}장 삭제 (여유 {shutil.disk_usage(OUT).free/1e9:.1f}GB)", flush=True)


def main():
    n = 0
    while True:
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            urllib.request.urlretrieve(URL, f"{OUT}/crop_{ts}.jpg")
            n += 1
            if n % CLEAN_EVERY == 0:
                cleanup_if_low()
                free_gb = shutil.disk_usage(OUT).free / 1e9
                cnt = len(glob.glob(os.path.join(OUT, "crop_*.jpg")))
                print(f"[{ts}] 누적 {cnt}장, 디스크 여유 {free_gb:.1f}GB", flush=True)
        except Exception as e:
            print(f"수집 오류: {e}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    print(f"수집 시작 → {OUT} (간격 {INTERVAL}s, 디스크 안전마진 {MIN_FREE_GB}GB)", flush=True)
    main()

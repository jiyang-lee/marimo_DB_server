# Arduino/Wemos 펌웨어 업로드 가이드

## 1) 대상 보드와 파일

### Wemos(ESP8266, MicroPython)

- 펌웨어 바이너리: `arduino/ESP8266_GENERIC-20260406-v1.28.0.bin`
- 실행 스크립트: `arduino/wemos_sensor_node/main.py`

### Nano

- 스케치 파일: `arduino/NanoPdmSerial.ino`

---

## 2) Python 3.12 가상환경 준비

```bash
cd /home/kdt-aiot/project/arduino_server
python3.12 -m venv .venv312
source .venv312/bin/activate
pip install -U pip
pip install -r arduino/requirements-uploader.txt
```

`requirements-uploader.txt`:

- `esptool`
- `mpremote`

---

## 3) 업로드 스크립트

통합 스크립트:

```bash
python arduino/upload_firmware.py --help
```

지원 명령:

- `esp8266-flash`
- `esp8266-push-main`
- `nano-upload`
- `all`

---

## 4) Wemos 업로드 절차 (현재 완료한 흐름)

### 1) ESP8266 MicroPython 펌웨어 플래시

```bash
python arduino/upload_firmware.py esp8266-flash --port /dev/ttyUSB0
```

### 2) main.py 업로드

```bash
python arduino/upload_firmware.py esp8266-push-main --port /dev/ttyUSB0
```

---

## 5) Wemos 시리얼 로그 확인

```bash
python -m serial.tools.miniterm /dev/ttyUSB0 115200
```

- 종료: `Ctrl + ]`
- 리셋 버튼을 누르면 부팅 로그를 다시 확인 가능

정상 동작 로그 예:

- `T: ... H: ... Lx: ...`
- API 연결 정상 시 `Realtime ingest: 200`
- 온습도/수위 갱신 타이밍에는 `Hourly ingest: 200`

오류 예:

- `Ingest error: [Errno 104] ECONNRESET`  
  → API 서버 미실행/접속 불가일 때 발생

---

## 6) 센서 수집 주기 및 API 분리 (현재 적용)

- 실시간(약 3초): 조도(`light`), 거리(`distance`), 소리(`sound`)
- 30분: 수위(`water_level`)
- 1시간: 온도(`temperature`), 습도(`humidity`)

Wemos 업로드 파일(`arduino/wemos_sensor_node/main.py`)에서:

- `POLL_SECONDS = 3`
- `WATER_READ_INTERVAL_MS = 30 * 60 * 1000`
- `TEMP_HUMID_READ_INTERVAL_MS = 60 * 60 * 1000`

API 전송 경로:

- 실시간: `POST /sensor/realtime-ingest`
- 1시간 테이블(온습도+수위): `POST /sensor/hourly-ingest`

---

## 7) Nano 업로드 절차 (필요 시)

### 1) 권한 스크립트 1회 실행

```bash
sudo "/home/kdt-aiot/.arduino15/packages/arduino/hardware/mbed_nano/4.5.0/post_install.sh"
```

### 2) 업로드

```bash
python arduino/upload_firmware.py nano-upload --port /dev/ttyACM0 --fqbn arduino:mbed_nano:nano33ble
```

참고:

- Nano 포트는 연결 시 `ls /dev/ttyACM*`로 확인

---

## 8) 실제로 발생했던 이슈와 해결

### 이슈 A: `--port` 에러 + `bash: /dev/ttyUSB0: 허가 거부`

원인:

- 명령을 줄바꿈으로 입력해서 `/dev/ttyUSB0`가 별도 명령으로 실행됨

해결:

- 한 줄로 입력

```bash
python arduino/upload_firmware.py esp8266-flash --port /dev/ttyUSB0
```

### 이슈 B: `Permission denied: '/dev/ttyUSB0'`

원인:

- 사용자에게 `dialout` 권한 없음

해결:

```bash
sudo usermod -aG dialout $USER
newgrp dialout
```

### 이슈 C: Nano 컴파일 시 `arduino.ino missing`

원인:

- 기본 스케치 경로가 폴더로 잡혀 Arduino CLI가 `arduino/arduino.ino`를 찾음

조치:

- `upload_firmware.py`에서 Nano 기본 스케치를 `NanoPdmSerial.ino`로 수정
- `.ino` 단일 파일도 임시 스케치 디렉터리로 스테이징 후 컴파일/업로드하도록 보완

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARDUINO_DIR = PROJECT_ROOT / "arduino"
TOOLS_DIR = PROJECT_ROOT / ".tools"
DEFAULT_ESP_FW = ARDUINO_DIR / "ESP8266_GENERIC-20260406-v1.28.0.bin"
DEFAULT_ESP_MAIN = ARDUINO_DIR / "wemos_sensor_node" / "main.py"
DEFAULT_NANO_SKETCH = ARDUINO_DIR / "NanoPdmSerial.ino"
PYTHON_BIN = sys.executable


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def find_arduino_cli() -> Path:
    found = shutil.which("arduino-cli")
    if found:
        return Path(found)

    local_cli = TOOLS_DIR / "arduino-cli"
    if local_cli.exists():
        return local_cli

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    archive_url = "https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Linux_64bit.tar.gz"
    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = Path(tmpdir) / "arduino-cli.tar.gz"
        print(f"Downloading arduino-cli from {archive_url}")
        urllib.request.urlretrieve(archive_url, archive_path)
        with tarfile.open(archive_path) as tf:
            tf.extractall(tmpdir)
        extracted_cli = Path(tmpdir) / "arduino-cli"
        shutil.copy2(extracted_cli, local_cli)
    os.chmod(local_cli, 0o755)
    return local_cli


def ensure_esptool() -> None:
    if shutil.which("python3.12") is None:
        raise RuntimeError("python3.12 not found. Install Python 3.12 first.")

    missing = []
    try:
        subprocess.run(
            [PYTHON_BIN, "-c", "import esptool"], check=True, capture_output=True
        )
    except subprocess.CalledProcessError:
        missing.append("esptool")
    try:
        subprocess.run(
            [PYTHON_BIN, "-c", "import mpremote"], check=True, capture_output=True
        )
    except subprocess.CalledProcessError:
        missing.append("mpremote")

    if missing:
        raise RuntimeError(
            "Missing Python packages: "
            + ", ".join(missing)
            + ". Activate your 3.12 venv and run "
            + f"`pip install -r {ARDUINO_DIR / 'requirements-uploader.txt'}`"
        )


def esp8266_flash(args: argparse.Namespace) -> None:
    ensure_esptool()
    firmware = Path(args.firmware).resolve()
    if not firmware.exists():
        raise FileNotFoundError(f"Firmware not found: {firmware}")

    run(
        [
            PYTHON_BIN,
            "-m",
            "esptool",
            "--chip",
            "esp8266",
            "--port",
            args.port,
            "--baud",
            str(args.baud),
            "erase_flash",
        ]
    )
    run(
        [
            PYTHON_BIN,
            "-m",
            "esptool",
            "--chip",
            "esp8266",
            "--port",
            args.port,
            "--baud",
            str(args.baud),
            "write_flash",
            "--flash_size=detect",
            "0x0",
            str(firmware),
        ]
    )


def esp8266_push_main(args: argparse.Namespace) -> None:
    ensure_esptool()
    source = Path(args.source).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source file not found: {source}")

    run([PYTHON_BIN, "-m", "mpremote", "connect", args.port, "fs", "cp", str(source), ":main.py"])
    run([PYTHON_BIN, "-m", "mpremote", "connect", args.port, "reset"])


def nano_upload(args: argparse.Namespace) -> None:
    cli = find_arduino_cli()
    sketch_path = Path(args.sketch).resolve()
    if not sketch_path.exists():
        raise FileNotFoundError(f"Sketch path not found: {sketch_path}")

    cleanup_dir: Path | None = None
    if sketch_path.is_file() and sketch_path.suffix.lower() == ".ino":
        cleanup_dir = Path(tempfile.mkdtemp(prefix="nano-sketch-"))
        sketch_name = sketch_path.stem
        sketch_dir = cleanup_dir / sketch_name
        sketch_dir.mkdir(parents=True, exist_ok=True)
        staged_sketch = sketch_dir / f"{sketch_name}.ino"
        shutil.copy2(sketch_path, staged_sketch)
        sketch_path = sketch_dir

    try:
        run([str(cli), "core", "update-index"])
        run([str(cli), "core", "install", "arduino:mbed_nano"])
        run([str(cli), "compile", "--fqbn", args.fqbn, str(sketch_path)])
        run([str(cli), "upload", "--fqbn", args.fqbn, "-p", args.port, str(sketch_path)])
    finally:
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def all_upload(args: argparse.Namespace) -> None:
    esp8266_flash(args)
    esp8266_push_main(args)
    nano_upload(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Firmware uploader for MiniPC migration")
    sub = parser.add_subparsers(dest="cmd", required=True)

    common_esp = argparse.ArgumentParser(add_help=False)
    common_esp.add_argument("--port", required=True, help="ESP8266 serial port (e.g. /dev/ttyUSB0)")
    common_esp.add_argument(
        "--firmware",
        default=str(DEFAULT_ESP_FW),
        help=f"ESP8266 firmware bin path (default: {DEFAULT_ESP_FW})",
    )
    common_esp.add_argument(
        "--source",
        default=str(DEFAULT_ESP_MAIN),
        help=f"MicroPython main.py path (default: {DEFAULT_ESP_MAIN})",
    )
    common_esp.add_argument("--baud", type=int, default=460800, help="Flashing baudrate")

    p_flash = sub.add_parser("esp8266-flash", parents=[common_esp], help="Flash ESP8266 MicroPython firmware")
    p_flash.set_defaults(func=esp8266_flash)

    p_push = sub.add_parser("esp8266-push-main", parents=[common_esp], help="Upload ESP8266 main.py")
    p_push.set_defaults(func=esp8266_push_main)

    p_nano = sub.add_parser("nano-upload", help="Compile and upload Nano sketch")
    p_nano.add_argument("--port", required=True, help="Nano serial port (e.g. /dev/ttyACM0)")
    p_nano.add_argument(
        "--fqbn",
        default="arduino:mbed_nano:nano33ble",
        help="Nano board FQBN",
    )
    p_nano.add_argument(
        "--sketch",
        default=str(DEFAULT_NANO_SKETCH),
        help=f"Arduino sketch path (default: {DEFAULT_NANO_SKETCH})",
    )
    p_nano.set_defaults(func=nano_upload)

    p_all = sub.add_parser(
        "all",
        parents=[common_esp],
        help="Run ESP8266 flash + main.py upload + Nano upload",
    )
    p_all.add_argument("--nano-port", required=True, help="Nano serial port (e.g. /dev/ttyACM0)")
    p_all.add_argument(
        "--fqbn",
        default="arduino:mbed_nano:nano33ble",
        help="Nano board FQBN",
    )
    p_all.add_argument(
        "--sketch",
        default=str(DEFAULT_NANO_SKETCH),
        help=f"Arduino sketch path (default: {DEFAULT_NANO_SKETCH})",
    )

    def all_wrapper(ns: argparse.Namespace) -> None:
        ns.port = ns.port
        ns.source = ns.source
        ns.firmware = ns.firmware
        ns.baud = ns.baud
        esp8266_flash(ns)
        esp8266_push_main(ns)
        nano_ns = argparse.Namespace(port=ns.nano_port, fqbn=ns.fqbn, sketch=ns.sketch)
        nano_upload(nano_ns)

    p_all.set_defaults(func=all_wrapper)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

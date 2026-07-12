"""protect — Hardware health and monitor protection module.

Features:
  - Turns off the monitor (using xset dpms).
  - Listens invisibly in terminal raw mode for a wake word.
  - Automatically turns the monitor back on when the wake word is typed.
  - Periodic hardware health logging (optional).

Usage:
  hnx prot [start]
  hnx prot bind set <word>
  hnx prot bind reset
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import termios
    import tty
    HAS_TERMIOS = True
except ImportError:
    HAS_TERMIOS = False

CONFIG_DIR = Path.home() / ".hypernix"
CONFIG_FILE = CONFIG_DIR / "protect.json"
DEFAULT_WAKE_WORD = "bon"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {"wake_word": DEFAULT_WAKE_WORD, "health_checks": True}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"wake_word": DEFAULT_WAKE_WORD, "health_checks": True}


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def set_wake_word(word: str) -> None:
    cfg = load_config()
    cfg["wake_word"] = word
    save_config(cfg)
    print(f"[protect] Wake word set to '{word}'.")


def reset_wake_word() -> None:
    cfg = load_config()
    cfg["wake_word"] = DEFAULT_WAKE_WORD
    save_config(cfg)
    print(f"[protect] Wake word reset to default '{DEFAULT_WAKE_WORD}'.")


def set_monitor_state(state: str) -> None:
    """Turn the monitor 'on' or 'off' using xset on Linux."""
    if sys.platform.startswith("linux"):
        try:
            subprocess.run(["xset", "dpms", "force", state], check=False, 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


def _health_monitor_thread(stop_event: threading.Event) -> None:
    """Optional periodic health check logging."""
    try:
        import psutil
    except ImportError:
        return

    while not stop_event.is_set():
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory().percent
        # Log to file to avoid breaking raw mode terminal
        log_file = CONFIG_DIR / "protect_health.log"
        try:
            with open(log_file, "a") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - CPU: {cpu}% MEM: {mem}%\n")
        except Exception:
            pass
        
        # Check every 60 seconds
        for _ in range(60):
            if stop_event.is_set():
                break
            time.sleep(1)


def start_protection() -> None:
    if not HAS_TERMIOS:
        print("Error: protect module requires a POSIX terminal (termios/tty).")
        sys.exit(1)

    cfg = load_config()
    wake_word = cfg.get("wake_word", DEFAULT_WAKE_WORD)
    do_health = cfg.get("health_checks", True)

    print(f"[protect] Entering protection mode.")
    print(f"[protect] Monitor will sleep. Type '{wake_word}' to wake up.")
    time.sleep(1.5)

    # Start health monitor
    stop_event = threading.Event()
    health_thread = None
    if do_health:
        health_thread = threading.Thread(target=_health_monitor_thread, args=(stop_event,), daemon=True)
        health_thread.start()

    set_monitor_state("off")

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    
    buffer = ""
    try:
        tty.setraw(sys.stdin.fileno())
        while True:
            char = sys.stdin.read(1)
            # Ctrl+C is ASCII 3
            if char == '\x03':
                break
            
            buffer += char
            # Keep buffer size manageable
            if len(buffer) > len(wake_word) * 2:
                buffer = buffer[-len(wake_word)*2:]
                
            if buffer.endswith(wake_word):
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        set_monitor_state("on")
        stop_event.set()
        if health_thread:
            health_thread.join(timeout=1.0)
        
    print("\n[protect] Waking up. Protection mode ended.")


def cli_main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    
    if not args or args[0] == "start":
        start_protection()
        return 0
        
    if args[0] == "bind":
        if len(args) < 2:
            print("Usage: hnx prot bind [set <word> | reset]")
            return 1
        
        if args[1] == "reset":
            reset_wake_word()
            return 0
            
        if args[1] == "set":
            if len(args) < 3:
                print("Error: Missing wake word.")
                return 1
            set_wake_word(args[2])
            return 0

    print("Usage:\n  hnx prot [start]\n  hnx prot bind [set <word> | reset]")
    return 1

if __name__ == "__main__":
    cli_main()

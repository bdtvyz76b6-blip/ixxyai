import json
import os
from threading import Lock

VIP_FILE = "vips.json"
lock = Lock()

def load_vips():
    if not os.path.exists(VIP_FILE):
        return set()
    with open(VIP_FILE) as f:
        return set(json.load(f))

def save_vips(vips):
    with open(VIP_FILE, "w") as f:
        json.dump(list(vips), f)

def is_vip(user_id: int) -> bool:
    return user_id in load_vips()

def add_vip(user_id: int):
    with lock:
        vips = load_vips()
        vips.add(user_id)
        save_vips(vips)
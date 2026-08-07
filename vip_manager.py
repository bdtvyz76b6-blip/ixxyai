import json
import os
from threading import Lock

VIP_FILE = "vips.json"
FREE_FILE = "free_usage.json"
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

def load_free_usage():
    if not os.path.exists(FREE_FILE):
        return {}
    with open(FREE_FILE) as f:
        return json.load(f)

def save_free_usage(data):
    with open(FREE_FILE, "w") as f:
        json.dump(data, f)

def can_use_free(user_id: int) -> bool:
    with lock:
        data = load_free_usage()
        used = data.get(str(user_id), 0)
        return used < FREE_LIMIT

def use_free(user_id: int):
    with lock:
        data = load_free_usage()
        uid = str(user_id)
        data[uid] = data.get(uid, 0) + 1
        save_free_usage(data)
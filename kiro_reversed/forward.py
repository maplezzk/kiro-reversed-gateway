# -*- coding: utf-8 -*-
"""
纯转发模式相关常量。
"""

import os


# Kiro official upstream hosts. Optional IP overrides can be provided when DNS
# resolution would loop back to the local proxy because of /etc/hosts hijacking.
KIRO_FORWARD_TARGETS = {
    "runtime": {
        "ip": os.getenv("KIRO_RUNTIME_IP", "").strip(),
        "host": os.getenv("KIRO_RUNTIME_HOST", "runtime.us-east-1.kiro.dev").strip(),
    },
    "management": {
        "ip": os.getenv("KIRO_MANAGEMENT_IP", "").strip(),
        "host": os.getenv("KIRO_MANAGEMENT_HOST", "management.us-east-1.kiro.dev").strip(),
    },
    "q": {
        "ip": os.getenv("KIRO_Q_IP", "").strip(),
        "host": os.getenv("KIRO_Q_HOST", "q.us-east-1.amazonaws.com").strip(),
    },
}

KIRO_FORWARD_HOSTS = {
    target["host"]: name for name, target in KIRO_FORWARD_TARGETS.items() if target.get("host")
}

KIRO_REAL_IPS = [target["ip"] for target in KIRO_FORWARD_TARGETS.values() if target.get("ip")]

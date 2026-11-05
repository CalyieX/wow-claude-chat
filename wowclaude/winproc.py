"""Every helper process this package starts must be invisible: no console window, no flashing window.
``subprocess.Popen(cmd, **hidden())``"""
from __future__ import annotations

import os
import subprocess

CREATE_NO_WINDOW = 0x08000000


def hidden() -> dict:
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return {"creationflags": CREATE_NO_WINDOW, "startupinfo": si}

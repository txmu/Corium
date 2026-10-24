#!/usr/bin/env python3
"""systemd ExecCondition: fail closed on an active or invalid local safety hold."""
import json
import os
from pathlib import Path
import stat
import sys


def start_permitted(path):
    try:
        metadata=Path(path).lstat()
    except FileNotFoundError:
        return True
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid!=os.geteuid()
            or metadata.st_mode & 0o077 or metadata.st_size>8192):
        return False
    try:
        value=json.loads(Path(path).read_text())
    except (OSError,ValueError,UnicodeError):
        return False
    return (type(value) is dict and value.get('schema')=='ziokt.consensus-safety-hold.v1'
            and type(value.get('active')) is bool and value['active'] is False)


if __name__=='__main__':
    raise SystemExit(0 if len(sys.argv)==2 and start_permitted(sys.argv[1]) else 1)

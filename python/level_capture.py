"""Immutable local evidence for completed drawing operations."""
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

MAX_BYTES = 4 * 1024 * 1024


def atomic_file(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError('Snapshot identity conflicts with existing evidence')
        return
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def record_completed(details_path, result, kind, *, wall=time.time):
    root = Path(details_path).parent
    completed = wall()
    snapshot = dict(version=1, id=str(uuid.uuid4()), producer='daily-levels',
                    kind=kind, symbol=result['symbol'], scope=result['scope'],
                    completed_at=completed, result=result | {'completed_at': completed})
    payload = json.dumps(snapshot, ensure_ascii=False, allow_nan=False,
                         separators=(',', ':')).encode('utf-8')
    if len(payload) > MAX_BYTES:
        raise ValueError('Completed drawing snapshot is too large')
    # Completed evidence survives later Draw, Clear, and theme changes.
    name = snapshot['id'] + '.json'
    atomic_file(root / 'level-snapshots' / name, payload)
    return dict(id=snapshot['id'], completed_at=completed,
                sha256=hashlib.sha256(payload).hexdigest())


def preserve_completed(client, result, kind):
    path = getattr(client, 'details_path', None)
    if path is None:
        return
    try:
        capture = record_completed(path, result, kind)
    except Exception as exc:
        raise RuntimeError('Chart updated, but its research snapshot could not be saved') from exc
    result['research_capture'] = capture
    result['completed_at'] = capture['completed_at']

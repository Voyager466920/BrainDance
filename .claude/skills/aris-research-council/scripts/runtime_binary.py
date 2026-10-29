"""Keep each frozen executable at an immutable path for lazy archive imports.

PyInstaller reopens its executable when importing. Replacing that path underneath
a live process mixes old archive offsets with new bytes, even after atomic rename.
"""
import hashlib
import os
from pathlib import Path
import tempfile


def pin(executable, directory):
    source = Path(executable).resolve()
    content = source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    folder = Path(directory).expanduser().resolve() / digest
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / 'BrainDanceServer'
    if source == target:
        return target
    if not target.exists():
        fd, temporary = tempfile.mkstemp(prefix='.install-', dir=folder)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o555)
            try:
                os.link(temporary, target)  # Never replace a possibly live image.
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Pinned BrainDance executable failed its integrity check')
    return target

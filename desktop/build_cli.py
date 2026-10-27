#!/usr/bin/env python3
"""Build the standalone CLI; no native app or Swift toolchain is required."""
import os
from pathlib import Path
import platform
import shutil
import sys
from build import build_backend,copy_notices,run,ROOT


def main():
    build,dist,architecture=build_backend()
    output=dist/'BrainDanceCLI'
    if output.exists():shutil.rmtree(output)
    output.mkdir()
    shutil.copy2(build/'server/BrainDanceServer',output/'BrainDanceServer')
    shutil.copy2(ROOT/'desktop/BrainDance.itermkeymap',output/'BrainDance.itermkeymap')
    copy_notices(output)
    if platform.system()=='Darwin':run('codesign','--verify','--strict',output/'BrainDanceServer')
    name='BrainDance-cli-'+('macOS' if platform.system()=='Darwin' else platform.system().lower())+'-'+architecture
    shutil.make_archive(str(dist/name),'zip',root_dir=dist,base_dir=output.name)
    print('Standalone CLI:',output)
    print('Archive:',dist/(name+'.zip'))


if __name__=='__main__':main()

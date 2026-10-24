#!/usr/bin/env python3
"""Build a native macOS .app with a bundled Python backend and no user data."""
import os
from importlib import metadata
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT/'.claude/skills/aris-research-council/scripts'


def run(*args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def main():
    if platform.system() != 'Darwin':
        raise SystemExit('Build the desktop app on macOS.')
    build, dist = ROOT/'build', ROOT/'dist'
    build.mkdir(exist_ok=True); dist.mkdir(exist_ok=True)
    architecture = platform.machine()
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
        '--name', 'BrainDanceServer', '--paths', SCRIPTS,
        '--add-data', str(SCRIPTS.parent/'assets')+':assets', '--collect-data', 'certifi',
        '--distpath', build/'server', '--workpath', build/'pyinstaller', '--specpath', build,
        '--target-architecture', architecture, ROOT/'desktop/backend.py')
    app = dist/'BrainDance.app'
    # Only replace the build output, never an installed app or user data.
    if app.exists():
        shutil.rmtree(app)
    resources = app/'Contents/Resources'; macos = app/'Contents/MacOS'
    resources.mkdir(parents=True); macos.mkdir()
    shutil.copy2(ROOT/'desktop/Info.plist', app/'Contents/Info.plist')
    shutil.copy2(build/'server/BrainDanceServer', resources/'BrainDanceServer')
    notices = resources/'ThirdPartyNotices'
    notices.mkdir()
    shutil.copy2(ROOT/'LICENSE', notices/'BrainDance-MIT.txt')
    for notice in (ROOT/'desktop/licenses').glob('*'):
        shutil.copy2(notice,notices/notice.name)
    shutil.copy2(Path(sys.base_prefix)/'lib'/('python'+str(sys.version_info.major)+'.'+str(sys.version_info.minor))/'LICENSE.txt',notices/'Python-LICENSE.txt')
    for package, filename in [('certifi','LICENSE'),('pyinstaller','COPYING.txt')]:
        distribution=metadata.distribution(package)
        source=next(distribution.locate_file(f) for f in distribution.files if f.name==filename and 'licenses' in f.parts)
        shutil.copy2(source,notices/(package+'-'+filename))
    env = os.environ.copy(); env['MACOSX_DEPLOYMENT_TARGET'] = '13.0'
    subprocess.run(['swiftc', '-swift-version', '5', '-O', '-gnone', '-target', architecture+'-apple-macosx13.0',
                    '-framework', 'AppKit', '-framework', 'WebKit', str(ROOT/'desktop/main.swift'),
                    '-o', str(macos/'BrainDance')], env=env, check=True)
    run('swiftc', '-O', ROOT/'desktop/MakeIcon.swift', '-o', build/'MakeIcon')
    run(build/'MakeIcon', build/'BrainDance.iconset')
    run('iconutil', '-c', 'icns', build/'BrainDance.iconset', '-o', resources/'BrainDance.icns')
    run('codesign', '--force', '--deep', '--sign', '-', app)
    run('codesign', '--verify', '--deep', '--strict', app)
    archive = dist/('BrainDance-macOS-'+architecture+'.zip')
    if archive.exists():
        archive.unlink()
    run('ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', app, archive)
    print('Built:', app)
    print('Archive:', archive)


if __name__ == '__main__':
    main()

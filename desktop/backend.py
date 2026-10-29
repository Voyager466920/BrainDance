"""Native app backend entry point; no research data belongs in the app bundle."""
import argparse
import errno
import json
import os
from pathlib import Path
import sys
import signal

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.claude/skills/aris-research-council/scripts'))

from compute import PROBE


def data_directory():
    override = os.environ.get('BRAINDANCE_DATA_DIR')
    return Path(override).expanduser().resolve() if override else Path.home() / 'Library/Application Support/BrainDance'


def main():
    paths = [str(Path.home()/'.local/bin'), '/opt/homebrew/bin', '/usr/local/bin',
             *os.environ.get('PATH', '').split(os.pathsep), '/usr/bin', '/bin']
    os.environ['PATH'] = os.pathsep.join(dict.fromkeys(paths))
    if getattr(sys, 'frozen', False):
        import certifi
        os.environ.setdefault('SSL_CERT_FILE', certifi.where())
    if sys.argv[1:2]==['--cli']:
        from terminal import main as cli_main
        raise SystemExit(cli_main(sys.argv[2:]))
    if sys.argv[1:]==['--install-cli']:
        from terminal import install_launcher
        print(install_launcher())
        return
    if sys.argv[1:2]==['--host-repair-worker']:
        from host_repair import run
        run(sys.argv[2],sys.argv[3])
        return
    if sys.argv[1:2]==['--native-shell']:
        from native_shell import main as shell_main
        shell_main(sys.argv[2])
        return
    if sys.argv[1:2]==['--native-helper']:
        from native_pipeline import Host
        job=json.loads(Path(sys.argv[2]).read_text());request=json.loads(Path(sys.argv[3]).read_text())
        result=Host(job).execute('helper',request)
        print(result['stdout'],end='');print(result['stderr'],end='',file=sys.stderr)
        raise SystemExit(result['returncode'])
    if sys.argv[1:2]==['--native-host']:
        from native_pipeline import serve
        serve(sys.argv[2])
        return
    if sys.argv[1:2]==['--research-worker']:
        from research_worker import run
        raise SystemExit(run(sys.argv[2]))
    if sys.argv[1:] == ['--probe-local']:
        # A frozen binary is not a Python interpreter. Run only the fixed hardware probe.
        exec(compile(PROBE, '<hardware-probe>', 'exec'), {'__name__': '__main__'})
        return
    if sys.argv[1:2]==['--experiment-worker']:
        from experiment_worker import main as worker_main
        worker_main()
        return
    if sys.argv[1:2]==['--run-experiment']:
        import runpy
        sys.argv=sys.argv[2:]
        # Match normal Python script semantics for unmodified upstream helpers
        # that import sibling modules (run_state, provenance, etc.).
        sys.path.insert(0,str(Path(sys.argv[0]).resolve().parent))
        runpy.run_path(sys.argv[0],run_name='__main__')
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=data_directory())
    parser.add_argument('--db', type=Path)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    def terminate(*_):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,terminate)
    database = args.db.expanduser().resolve() if args.db else args.data_dir.expanduser().resolve()/'tree.sqlite3'
    directory = database.parent
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if getattr(sys, 'frozen', False):
        from runtime_binary import pin
        executable = pin(sys.executable, directory/'runtime-binaries')
        if executable != Path(sys.executable).resolve():
            environment = os.environ.copy()
            environment['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
            certificate = environment.get('SSL_CERT_FILE')
            if certificate and Path(certificate).is_relative_to(Path(sys._MEIPASS)):
                environment.pop('SSL_CERT_FILE')
            os.execve(str(executable), [str(executable), *sys.argv[1:]], environment)
    from viewer import create_server
    try:
        server = create_server(database, args.port, max_depth=3)
    except OSError as error:
        if error.errno != errno.EADDRINUSE or args.port == 0:
            raise
        server = create_server(database, 0, max_depth=3)
    with server:
        print(json.dumps({'app': 'BrainDance', 'url': 'http://127.0.0.1:'+str(server.server_address[1])+'/'}), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()

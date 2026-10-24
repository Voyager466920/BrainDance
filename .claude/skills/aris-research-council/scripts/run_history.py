"""Import retained Council requests and outputs without another model invocation."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from tree_store import TreeStore


def import_run(store, run):
    run = Path(run).resolve()
    # Only completed runs can expose identities; the blind-review inputs stay untouched.
    if json.loads((run / 'status.json').read_text()).get('status') != 'completed':
        raise ValueError('Only completed Council runs can be imported')
    count = 0
    def record(round_number, phase, participant, direction, source, content):
        nonlocal count
        key = '|'.join([str(run), str(round_number), phase, participant, direction, str(source)])
        store.record_message(dict(id=hashlib.sha256(key.encode()).hexdigest(), run_id=str(run),
            round=round_number, phase=phase, participant=participant, direction=direction,
            content=content, source=str(source.relative_to(run)),
            created_at=datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat()))
        count += 1
    for folder in sorted(run.glob('round-*')):
        number = int(folder.name.split('-')[-1])
        for phase in ('generation', 'peer-review'):
            for agents_file in sorted((folder / phase).glob('claude-wave-*/agents.json')):
                definitions = json.loads(agents_file.read_text())
                parsed = agents_file.with_name('parsed.json')
                answers = json.loads(parsed.read_text())
                for role, answer in answers.items():
                    record(number, phase, 'Claude · ' + role, 'request', agents_file,
                           definitions['council-' + role]['prompt'])
                    record(number, phase, 'Claude · ' + role, 'response', parsed,
                           json.dumps(answer, ensure_ascii=False, indent=2))
            request = folder / phase / 'codex/request.json'
            response = request.with_name('response.txt')
            if request.is_file():
                record(number, phase, 'Codex', 'request', request,
                       json.loads(request.read_text())['params']['arguments']['prompt'])
            if response.is_file():
                record(number, phase, 'Codex', 'response', response, response.read_text())
        prompt = folder / 'chairman/chairman.prompt.txt'
        response = folder / 'chairman/parsed.json'
        if prompt.is_file():
            record(number, 'chairman', 'Claude · Chairman', 'request', prompt, prompt.read_text())
        if response.is_file():
            record(number, 'chairman', 'Claude · Chairman', 'response', response, response.read_text())
    return count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    print(json.dumps({'imported': import_run(TreeStore(args.db), args.run)}))

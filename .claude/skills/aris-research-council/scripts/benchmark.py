#!/usr/bin/env python3
"""Paired, measured context microbenchmark; not a whole-council quality evaluation."""
import argparse
import json
from pathlib import Path

from council import Budget, DEFAULTS, MODES, claude_call, codex_call, dump, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='Existing council output with both context variants')
    parser.add_argument('--output', required=True)
    parser.add_argument('--aris-repo', default=str(Path.home() / 'aris_repo'))
    args = parser.parse_args()
    source, out = Path(args.run).resolve(), Path(args.output).resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError('Benchmark output must be empty; do not overwrite receipts')
    out.mkdir(parents=True, exist_ok=True)
    config = {**DEFAULTS, **MODES['balanced'], 'output_tokens': 1024,
              'max_model_calls': 4, 'token_budget': 250000}
    budget = Budget(config, out / 'usage.json')
    expected = set(json.loads((source/'evidence-pack.json').read_text())['selected_ids'])
    rows = []
    instruction = ('Use ONLY the supplied primary evidence records (not incidental related-work mentions). '
                   'Do not use tools, delegate, browse, read files, or run experiments. '
                   'Return ONLY JSON with evidence_ids (arXiv IDs of the primary paper records) '
                   'and caveat (one sentence on the limits of abstract-only evidence).\n')
    for variant, filename in [('before', 'context-full.txt'), ('after', 'context-compact.txt')]:
        context = (source / filename).read_text()
        prompt = instruction + '\nEVIDENCE:\n' + context
        for provider in ['anthropic', 'openai']:
            folder = out / provider / variant
            if provider == 'anthropic':
                answer = claude_call(folder, 'context-microbenchmark', prompt, config['generation_model'],
                                     config, budget, required=('evidence_ids', 'caveat'))
            else:
                answer = codex_call(folder, prompt, config, budget, args.aris_repo)
            usage = json.loads((folder / 'usage.json').read_text())
            dump(folder / 'answer.json', answer)
            row = dict(provider=provider, variant=variant,
                       configured_model=config['generation_model'] if provider == 'anthropic' else config['codex_model'],
                       evidence_ids_correct=set(answer.get('evidence_ids', [])) == expected,
                       usage=usage['usage'], total_tokens=usage['total_tokens'])
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    comparisons = []
    for provider in ['anthropic', 'openai']:
        before, after = [r for r in rows if r['provider'] == provider]
        delta = before['total_tokens'] - after['total_tokens']
        comparisons.append(dict(provider=provider, before_tokens=before['total_tokens'],
                                after_tokens=after['total_tokens'], difference=delta,
                                reduction_percent=round(100*delta/before['total_tokens'], 2),
                                both_outputs_correct=before['evidence_ids_correct'] and after['evidence_ids_correct']))
    report = dict(scope='One paired primary-paper-ID extraction task per provider, n=1 per variant. Not a whole-pipeline A/B or research-quality equivalence test.',
                  measurement='Actual CLI/MCP cumulative token fields, including cache-read/creation where reported. Before runs first; cache/order and output/reasoning variation can affect results.',
                  models_fixed_within_provider=True, comparisons=comparisons, observations=rows)
    dump(out / 'comparison.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

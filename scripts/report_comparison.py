"""Render a saved comparison as Markdown without making any API calls."""
import argparse
import json
from pathlib import Path


def display(value):
    if value is None:
        return 'Not measured'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, float):
        return f'{value:,.3f}'
    return str(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    run = json.loads(args.run.read_text(encoding='utf-8'))
    tiers = run['tiers']
    benchmark = run['benchmark']
    rows = ['# Nano / Super / Ultra bounded comparison', '',
            f"Fixture: `{run['fixture']}`. Run: `{run['id']}`. Status: {run['status']}.", '',
            'One independent attempt per selected model. All compilation and candidate execution use Nebius Sandbox.',
            f"Required verification: {run['verification_runs']} runs per accepted candidate. Output cap: 2,048 tokens per model; no retries or escalation.", '',
            '| Metric | ' + ' | '.join(tiers) + ' |',
            '|---|' + '---|' * len(tiers)]
    for label, field in [('Input tokens','input_tokens'),('Output tokens','output_tokens'),('Total tokens','total_tokens'),
                         ('Reasoning tokens','reasoning_tokens'),('Inference time (ms)','inference_ms'),
                         ('Effective output tokens/s','effective_output_tokens_per_second'),
                         ('End-to-end time (ms)','end_to_end_ms'),('Baseline failures','baseline_failures'),
                         ('Patch accepted','patch_accepted'),('Added lines','patch_added_lines'),('Removed lines','patch_removed_lines'),
                         ('Candidate build passed','build_passed'),('Verification runs','verification_runs'),
                         ('Verification passes','verification_passes'),('Verification time (ms)','verification_ms'),
                         ('Deadlocks','deadlocks'),('Races','races'),('Crashes','crashes'),
                         ('Infrastructure failures','infrastructure_failures'),('Verified','verified'),
                         ('Inference cost estimate (USD)','estimated_inference_cost_usd'),('Finish reason','finish_reason'),
                         ('Inference error','error_code')]:
        rows.append('| ' + label + ' | ' + ' | '.join(display(benchmark['individual'][t].get(field)) for t in tiers) + ' |')
    rows += ['', '## Combined measurements', '', '```json', json.dumps(benchmark['combined'], indent=2), '```', '',
             '## Interpretation limits', ''] + ['- ' + note for note in benchmark['notes']]
    rows += ['- Super uses thinking disabled; Nano and Ultra retain provider defaults. This compares the configured application paths under the same output cap.',
             '- Input content is bounded to 12,000 UTF-8 bytes per request. Reported input tokens are actual provider usage.', '',
             '## Outputs', '']
    for tier in tiers:
        item = run['results'][tier]
        rows += ['### ' + tier, '', f"Model: `{item['model']}`", '',
                 f"Outcome: {item.get('job', {}).get('status', item['status'])}.", '', '```json', item.get('response', 'No response available.'), '```', '']
        for repair in item.get('job', {}).get('repairs', []):
            rows += ['```diff', repair.get('proposal', {}).get('patch', ''), '```', '']
    destination = args.run.with_suffix('.md')
    destination.write_text('\n'.join(rows), encoding='utf-8')
    print(destination)


if __name__ == '__main__':
    main()

"""Presenter-controlled first deployment of one Nemotron/vLLM replica."""
from __future__ import annotations

import argparse
import functools
from pathlib import Path
import sys
import time

from demos.common import runtime as ui
from demos.single_replica import agentx

STEPS = [
    ('The deployment', 'One CPU HTTP frontend and one vLLM worker replica using two H100s.'),
    ('Deploy and start', 'Follow Pod startup, model loading, and engine initialization through readiness.'),
    ('The HTTP endpoint', 'Forward the frontend Service and check the advertised model.'),
    ('Make a request', 'Send a small request through the frontend to the GPU worker.'),
    ('AIPerf: one agent', 'Replay one AgentX coding session for 20 s at concurrency 1: the command and its report.'),
    ('AIPerf: eight agents', 'The same slice at concurrency 8: eight sessions share the one replica.'),
]


class IntroDemo(ui.Demo):
    steps = STEPS

    # Overridden here rather than in the shared runtime: staged runs freeze runtime.py's hash.
    def guided(self):
        self.require_prepared()
        if not self.args.auto and not sys.stdin.isatty():
            raise RuntimeError('Interactive steps need a terminal. Use --preview, or --rehearsal --plain --auto.')
        mode = 'REHEARSAL / SIMULATED OUTPUT / NO CLUSTER CALLS' if self.args.rehearsal else 'LIVE CLUSTER'
        print(f'\nDynamo workshop · First deployment\n{mode}\nRun: {ui.repo_path(self.path)}\nNamespace: {self.ns}', flush=True)
        self.run_steps(self.steps, self.actions())

    def actions(self):
        return ([self.deployment, self.startup, self.endpoint, self.request] +
                [functools.partial(self.aiperf, c) for c in agentx.CONCURRENCY])

    def aiperf(self, concurrency):
        lock = ui.read_json(ui.MODEL_LOCK)
        name = agentx.artifact_name(self.path, concurrency)
        command = agentx.groups(lock, self.data['base_url'], concurrency, name)
        print('\n$ ' + agentx.projected(command), flush=True)
        self.pause()
        if self.args.rehearsal:
            print('[REHEARSAL] AIPerf is not run. Live, it sends this slice for 20 s against the endpoint and prints '
                  'its report here: time to first token, inter-token latency, request latency, throughput, errors.')
            return
        if agentx.staged(lock) is None:
            print('AIPerf is not staged on this host, so this step is skipped. '
                  'Offstage: python -m demos single-replica prepare-aiperf')
            return
        receipt = agentx.run(command, self.path)
        receipt['artifact_dir'] = name
        ui.write_json(self.path / (name + '.json'), receipt)
        self.data.setdefault('agentx', {})[str(concurrency)] = {
            key: receipt[key] for key in ('artifact_dir', 'exit_code', 'timed_out', 'started_at', 'ended_at')}
        self.save()
        if receipt['timed_out']:
            print(f'\nAIPerf ran past {agentx.TIMEOUT} s and was stopped. The service keeps running.')
        elif receipt['exit_code']:
            print(f'\nAIPerf exited with code {receipt["exit_code"]}; see {name}/logs/aiperf.log. '
                  'The service keeps running.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='run',
                        choices=['run', 'prepare', 'prepare-aiperf', 'preview', 'cleanup', 'observe', 'hold'],
                        help='prepare-aiperf stages AIPerf and the AgentX slice for steps 5-6 on this host; '
                             'it makes no cluster calls and selects no run.')
    parser.add_argument('--run', type=Path,
                        help='Select a specific run. By default, run/cleanup use the last successfully prepared live run; prepare creates a fresh run.')
    parser.add_argument('--rehearsal', action='store_true', help='Clearly labeled simulated output; makes no cluster calls.')
    parser.add_argument('--preview', action='store_true', help='Print the projected YAML excerpt and steps; no cluster calls.')
    parser.add_argument('--full-manifest', action='store_true',
                        help='Preview the full executable DGD instead of the projected excerpt; no cluster calls.')
    parser.add_argument('--plain', action='store_true', help='Use one terminal instead of creating a tmux layout.')
    parser.add_argument('--auto', action='store_true', help='Advance without keypresses (useful for scripted rehearsals).')
    parser.add_argument('--detach', action='store_true', help='Create the tmux layout without attaching.')
    parser.add_argument('--port', type=int, default=18000, help='Loopback port for the HTTP frontend (default: 18000).')
    parser.add_argument('--timeout', type=int, default=2700, help='Worker readiness timeout in seconds.')
    parser.add_argument('--view', choices=['resources', 'logs'], default='resources')
    parser.add_argument('--once', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.full_manifest:
        args.preview = True
    if not 0 < args.port < 65536 or args.timeout <= 0:
        parser.error('Port must be 1..65535 and timeout must be positive.')
    if args.action == 'hold':
        while True:
            time.sleep(60)
    if args.action == 'prepare-aiperf':
        agentx.stage(ui.read_json(ui.MODEL_LOCK))
        return
    if args.action == 'observe':
        if not args.run:
            parser.error('observe needs --run')
        ui.observe(args.run.resolve(), args.view, args.once)
        return
    if not args.run and args.action in ('run', 'cleanup') and not (args.rehearsal or args.preview):
        args.run = ui.current_run()
    if args.action == 'cleanup' and not args.run:
        parser.error('Rehearsal cleanup needs --run')
    demo = IntroDemo(args)
    print('Demo files: ' + ui.repo_path(demo.path), flush=True)
    if args.preview or args.action == 'preview':
        print((demo.path / 'deployment.yaml').read_text() if args.full_manifest else demo.write_excerpt().read_text())
        print('Full executable manifest: ' + ui.repo_path(demo.path / 'deployment.yaml'))
        print('GPU claim template: ' + ui.repo_path(demo.path / 'gpu-claim-template.yaml'))
        print('\nGuided steps:')
        for index, (title, explanation) in enumerate(STEPS, 1):
            print(f'{index}. {title}: {explanation}')
        print('\nLayout: presenter 58% left; resources/timing upper right; worker logs lower right.')
        print('Preview only: no cluster commands executed.')
    elif args.action == 'prepare':
        with ui.presenter_lock(demo.path):
            demo.prepare()
            ui.remember_prepared(demo)
        if not args.rehearsal and agentx.staged(ui.read_json(ui.MODEL_LOCK)) is None:
            print('AIPerf steps 5-6 are not staged on this host yet. Offstage: python -m demos single-replica prepare-aiperf')
    elif args.action == 'cleanup':
        with ui.presenter_lock(demo.path):
            demo.cleanup()
            ui.forget_cleaned(demo.path)
    else:
        demo.require_prepared()
        ui.remember_prepared(demo)
        if args.plain:
            with ui.presenter_lock(demo.path):
                demo.guided()
        else:
            ui.tmux_layout(demo)



if __name__ == "__main__":
    main()

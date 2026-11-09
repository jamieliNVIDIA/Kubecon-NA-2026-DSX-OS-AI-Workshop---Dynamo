"""Resolve source identities retained in immutable demo receipts.

Historical receipts identify sources by their original unique basename. These
aliases locate the reorganized files; every caller still verifies source hashes.
New receipts and remote bundles can use repository-relative source paths.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'analyze_workshop_disagg.py': 'scripts/development/disaggregated/analyze.py',
    'capture_workshop_demo.py': 'demos/common/capture.py',
    'inspect_shadow_reader_sources.py': 'demos/shadow/inspect_reader_sources.py',
    'inspect_workshop_disagg_cpu.py': 'scripts/development/disaggregated/inspect_client.py',
    'inspect_workshop_disagg_sources.py': 'scripts/development/disaggregated/inspect_sources.py',
    'mx_dev_cache_probe.py': 'scripts/development/mx_cache/probe.py',
    'mx_dev_cache_seed_v3.py': 'scripts/development/mx_cache/seed.py',
    'mx_dev_cache_stage.py': 'scripts/development/mx_cache/stage.py',
    'overnight_disagg_controller.py': 'scripts/development/disaggregated/controller.py',
    'prepare_kvcr_demo_sources.py': 'demos/kvcr/prepare_sources.py',
    'prepare_snapshot_nvme_demo.py': 'demos/snapshot/prepare_nvme.py',
    'probe_workshop_disagg_client.py': 'scripts/development/disaggregated/probe_client.py',
    'recheck_workshop_disagg_client.py': 'scripts/development/disaggregated/recheck_client.py',
    'recover_workshop_disagg_cpu.py': 'scripts/development/disaggregated/recover_client.py',
    'recover_workshop_disagg_profile.py': 'scripts/development/disaggregated/recover_profile.py',
    'render_mx_dev_cache_probe.py': 'scripts/development/mx_cache/render_probe.py',
    'render_mx_dev_cache_server_v3.py': 'scripts/development/mx_cache/render_server.py',
    'verify_workshop_disagg_results.py': 'scripts/development/disaggregated/verify.py',
    'verify_workshop_migration_load.py': 'demos/request_continuity/verify_load.py',
    'workshop_demo.py': 'demos/common/runtime.py',
    'workshop_demo_allocation.py': 'demos/common/allocation.py',
    'workshop_demo_support.py': 'demos/common/support.py',
    'workshop_disagg_benchmark.py': 'scripts/development/disaggregated/benchmark.py',
    'workshop_disagg_demo.py': 'demos/disaggregated/demo.py',
    'workshop_disagg_handoff.py': 'scripts/development/disaggregated/handoff.py',
    'workshop_kvcr_demo.py': 'demos/kvcr/demo.py',
    'workshop_kvcr_guard.py': 'demos/kvcr/guard.py',
    'workshop_kvcr_prepared.py': 'demos/kvcr/prepared.py',
    'workshop_metrics_demo.py': 'demos/metrics/demo.py',
    'workshop_migration_demo.py': 'demos/request_continuity/demo.py',
    'workshop_migration_evidence.py': 'demos/request_continuity/evidence.py',
    'workshop_migration_load.py': 'demos/request_continuity/load.py',
    'workshop_migration_probe.py': 'demos/request_continuity/probe.py',
    'workshop_modelexpress_demo.py': 'demos/modelexpress/demo.py',
    'workshop_mx_dev_cache.py': 'scripts/development/mx_cache/workflow.py',
    'workshop_presenter.py': 'demos/common/presenter.py',
    'workshop_routing_c16.py': 'demos/routing/recording.py',
    'workshop_routing_demo.py': 'demos/routing/demo.py',
    'workshop_run_selection.py': 'demos/common/selection.py',
    'workshop_shadow_composed.py': 'demos/shadow/composed.py',
    'workshop_shadow_demo.py': 'demos/shadow/demo.py',
    'workshop_shadow_descriptor_cpu_v4.py': 'demos/shadow/writer_cpu.py',
    'workshop_shadow_descriptor_writer.py': 'demos/shadow/descriptor_writer.py',
    'workshop_shadow_descriptors.py': 'demos/shadow/compat/descriptor_prototype.py',
    'workshop_shadow_descriptors_v2.py': 'demos/shadow/compat/descriptor_linear.py',
    'workshop_shadow_descriptors_v3.py': 'demos/shadow/compat/descriptor_attention.py',
    'workshop_shadow_descriptors_v4.py': 'demos/shadow/writer_descriptors.py',
    'workshop_shadow_descriptors_v5.py': 'demos/shadow/compat/descriptor_native_config.py',
    'workshop_shadow_descriptors_v6.py': 'demos/shadow/reader_descriptors.py',
    'workshop_shadow_diagnose.py': 'demos/shadow/diagnose.py',
    'workshop_shadow_diagnostics.py': 'demos/shadow/diagnostics.py',
    'workshop_shadow_extra_sources.py': 'demos/shadow/extra_sources.py',
    'workshop_shadow_follow_policy.py': 'demos/shadow/follow_policy.py',
    'workshop_shadow_full_remote.py': 'demos/shadow/full_remote.py',
    'workshop_shadow_full_remote_controller.py': 'demos/shadow/full_remote_controller.py',
    'workshop_shadow_humming.py': 'demos/shadow/humming.py',
    'workshop_shadow_inventory_analysis.py': 'demos/shadow/inventory_analysis.py',
    'workshop_shadow_parameter_inventory.py': 'demos/shadow/parameter_inventory.py',
    'workshop_shadow_reader.py': 'demos/shadow/reader.py',
    'workshop_shadow_reader_cpu_v5.py': 'demos/shadow/reader_packet.py',
    'workshop_shadow_reader_cpu_v6.py': 'demos/shadow/reader_cpu.py',
    'workshop_shadow_reader_delta.py': 'demos/shadow/compat/native_config_delta.py',
    'workshop_shadow_reader_delta_v6.py': 'demos/shadow/reader_delta.py',
    'workshop_shadow_runner_inspect.py': 'demos/shadow/runner_inspect.py',
    'workshop_shadow_runtime.py': 'demos/shadow/runtime.py',
    'workshop_shadow_runtime_inventory.py': 'demos/shadow/runtime_inventory.py',
    'workshop_shadow_writer.py': 'demos/shadow/writer.py',
    'workshop_shadow_writer_remote.py': 'demos/shadow/writer_remote.py',
    'workshop_shadow_writer_remote_controller.py': 'demos/shadow/writer_remote_controller.py',
    'workshop_snapshot_capture_deadline.py': 'demos/snapshot/capture_deadline.py',
    'workshop_snapshot_controller_image.py': 'demos/snapshot/controller_image.py',
    'workshop_snapshot_demo.py': 'demos/snapshot/demo.py',
    'workshop_snapshot_dgd.py': 'demos/snapshot/dgd.py',
    'workshop_snapshot_dgd_demo.py': 'demos/snapshot/dgd_demo.py',
    'workshop_snapshot_nvme.py': 'demos/snapshot/nvme.py',
    'workshop_snapshot_remote.py': 'demos/snapshot/remote.py',
    'workshop_snapshot_remote_controller.py': 'demos/snapshot/remote_controller.py',
}


def source_path(name, *, root=ROOT):
    name = str(name)
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Source must be a safe repository-relative path.')
    if len(relative.parts) > 1:
        return Path(root) / relative
    return Path(root) / SOURCES.get(name, 'scripts/' + name)


def source_files(root=ROOT):
    root = Path(root)
    return sorted({p for p in (root / 'scripts').rglob('*.py') if '__pycache__' not in p.parts} |
                  {p for p in (root / 'demos').rglob('*.py')
                   if '__pycache__' not in p.parts and 'transcripts' not in p.relative_to(root / 'demos').parts})


def source_name(path, *, root=ROOT):
    """Keep historical unique source keys while avoiding collisions such as demo.py."""
    path = Path(path).resolve()
    try:
        relative = path.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return path.name
    return next((name for name, target in SOURCES.items() if target == relative), relative)

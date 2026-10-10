"""The drift sensor against a real (ephemeral) Dagster instance: an asset sensor gets an EventLogEntry."""

import dagster as dg

from labpipes.definitions import defs
from labpipes.defs.drift import drift_sensor
from labpipes.partitions import trip_months


def materialize(instance: dg.DagsterInstance, key: str, partition: str, **metadata) -> None:
    instance.report_runless_asset_event(dg.AssetMaterialization(asset_key=key, partition=partition, metadata=metadata))


def test_new_features_request_one_drift_run_per_materialization():
    with dg.instance_for_test() as instance, dg.partition_loading_context(dynamic_partitions_store=instance):
        instance.add_dynamic_partitions(trip_months.name, ["2025-01"])
        materialize(instance, "trip_features", "2025-01")
        first = drift_sensor.evaluate_tick(dg.build_sensor_context(instance=instance, definitions=defs))
        assert [r.partition_key for r in first.run_requests] == ["2025-01"]
        materialize(instance, "trip_features", "2025-01")
        second = drift_sensor.evaluate_tick(dg.build_sensor_context(instance=instance, definitions=defs, cursor=first.cursor))
        assert [r.partition_key for r in second.run_requests] == ["2025-01"]
        assert second.run_requests[0].run_key != first.run_requests[0].run_key

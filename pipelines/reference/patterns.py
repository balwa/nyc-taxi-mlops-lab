"""Reference patterns for Dagster 1.13 (the pinned version): one partitioned asset, one blocking asset
check, one sensor. Copy the shapes, not the domain: this file loads weather readings, not trips.

Not loaded by the code location (only labpipes.defs is). `make test-pipelines` checks it still builds.
Docs for this version: https://docs.dagster.io/ (assets, asset checks, sensors, dynamic partitions).
"""

import json

import dagster as dg

from labpipes.resources import DataBucket, RedshiftData

# Dynamic partitions: the set of keys grows as data shows up (a sensor adds them).
stations = dg.DynamicPartitionsDefinition(name="stations")


# 1. A partitioned asset. Resources arrive as typed parameters. pool= limits concurrency (dagster.yaml).
@dg.asset(partitions_def=stations, group_name="example", kinds={"redshift"}, pool="redshift")
def readings(context: dg.AssetExecutionContext, redshift: RedshiftData) -> dg.MaterializeResult:
    station = context.partition_key
    # Several statements in one call run as one transaction (see RedshiftData.execute).
    redshift.execute(
        "create table if not exists example.readings (station varchar(16), celsius double precision)",
        f"delete from example.readings where station = '{station}'",
        f"insert into example.readings values ('{station}', 21.5)",
    )
    n = redshift.scalar(f"select count(*) from example.readings where station = '{station}'")
    return dg.MaterializeResult(metadata={"rows": dg.MetadataValue.int(int(n))})


# 2. A blocking asset check on the same partitions. blocking=True: if it fails, assets downstream of
#    `readings` in the same run don't execute.
@dg.asset_check(asset=readings, partitions_def=stations, blocking=True, description="Temperatures are plausible.")
def plausible_temperatures(context: dg.AssetCheckExecutionContext, redshift: RedshiftData) -> dg.AssetCheckResult:
    bad = redshift.scalar(
        f"select count(*) from example.readings where station = '{context.partition_key}' "
        "and celsius not between -60 and 60"
    )
    return dg.AssetCheckResult(
        passed=int(bad) == 0,
        severity=dg.AssetCheckSeverity.ERROR,  # WARN for a non-blocking signal
        description=f"{bad} implausible reading(s)",
        metadata={"bad_rows": dg.MetadataValue.int(int(bad))},
    )


# 3. A sensor that turns new objects into partitions and runs. The cursor remembers what was requested;
#    run_key makes a repeated request a no-op.
readings_job = dg.define_asset_job("readings_job", selection=dg.AssetSelection.assets(readings))


@dg.sensor(job=readings_job, minimum_interval_seconds=60)
def new_stations(context: dg.SensorEvaluationContext, data_bucket: DataBucket):
    seen = set(json.loads(context.cursor or "[]"))
    found = {f.month for f in data_bucket.trip_files()}  # stand-in for "list the new objects"
    new = sorted(found - seen)
    if not new:
        return dg.SkipReason("nothing new")
    return dg.SensorResult(
        run_requests=[dg.RunRequest(partition_key=k, run_key=k) for k in new],
        dynamic_partitions_requests=[stations.build_add_request(new)],
        cursor=json.dumps(sorted(seen | set(new))),
    )


# Resources are bound once, by key; every asset, check and sensor asks for them by parameter name.
defs = dg.Definitions(
    assets=[readings],
    asset_checks=[plausible_temperatures],
    jobs=[readings_job],
    sensors=[new_stations],
    resources={
        "redshift": RedshiftData(cluster_id="lab", database="lab", db_user="labadmin"),
        "data_bucket": DataBucket(bucket="example-bucket"),
    },
)

"""Read what an earlier asset recorded, so a later step uses exactly the version it produced."""

import dagster as dg


def last_metadata(instance: dg.DagsterInstance, asset: str) -> dict:
    """The metadata values of an asset's latest materialization ({} if it has none)."""
    records = instance.fetch_materializations(dg.AssetKey(asset), limit=1).records
    if not records:
        return {}
    return {k: v.value for k, v in records[0].asset_materialization.metadata.items()}

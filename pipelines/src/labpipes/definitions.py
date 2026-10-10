"""The code location: every definition in labpipes.defs, plus the resources they share.

Resources read their settings from the environment (contracts/runtime.yaml and platform.yaml name the
variables): LAB_DATA_BUCKET, REDSHIFT_CLUSTER_ID, REDSHIFT_DATABASE, REDSHIFT_DB_USER,
LAB_ARTIFACT_BUCKET, MLFLOW_TRACKING_URI and (S6) LLM_HOST.
"""

import dagster as dg

from . import defs as defs_package
from .resources import ArtifactBucket, DataBucket, LlmEmbed, MlflowTracking, RagStore, RedshiftData, WikiApi

# Assets that write to Redshift share the "redshift" pool, limited to one at a time (dagster.yaml):
# concurrent deletes and inserts on the same table abort with serializable isolation errors.
defs = dg.load_definitions_from_package_module(
    defs_package,
    resources={
        "redshift": RedshiftData(
            cluster_id=dg.EnvVar("REDSHIFT_CLUSTER_ID"),
            database=dg.EnvVar("REDSHIFT_DATABASE"),
            db_user=dg.EnvVar("REDSHIFT_DB_USER"),
        ),
        "data_bucket": DataBucket(bucket=dg.EnvVar("LAB_DATA_BUCKET")),
        "artifacts": ArtifactBucket(bucket=dg.EnvVar("LAB_ARTIFACT_BUCKET")),
        "tracking": MlflowTracking(tracking_uri=dg.EnvVar("MLFLOW_TRACKING_URI")),
        "wiki": WikiApi(),
        "embed": LlmEmbed(llm_host=dg.EnvVar("LLM_HOST")),
        "rag": RagStore(),
    },
)

"""Trip-duration models shared by the notebook, the pipeline (S2) and serving (S3).

No Dagster and no AWS here: pandas in, minutes out. MLflow logs these as pyfunc models with this
package bundled (code_paths), so serving can load a model without the pipeline's code.
"""

from .model import (
    FEATURES,
    LABEL,
    REQUIRED,
    BaselineModel,
    DistanceLookup,
    LightGBMModel,
    evaluate,
    model_signature,
)

__all__ = [
    "FEATURES",
    "LABEL",
    "REQUIRED",
    "BaselineModel",
    "DistanceLookup",
    "LightGBMModel",
    "evaluate",
    "model_signature",
]

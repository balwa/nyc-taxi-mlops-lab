import os
import sys
from pathlib import Path

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
# tripmodel, to train the models the tests register (the image doesn't need it: models carry it).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines" / "src"))

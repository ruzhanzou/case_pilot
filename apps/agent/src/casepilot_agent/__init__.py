"""CasePilot Agent package."""

import os

# Set before optional markitdown/magika imports initialize ONNX native telemetry.
os.environ["ORT_DISABLE_TELEMETRY"] = "1"

__version__ = "0.1.0"

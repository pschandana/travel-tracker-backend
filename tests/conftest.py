"""
conftest.py — shared pytest configuration for backend tests.

Stubs out TensorFlow and ml_model before any test module is imported.
TensorFlow's native DLL may fail to load in CI/test environments; the
tests don't exercise ML functionality so a lightweight stub is sufficient.
"""

import sys
import types


def _stub_tensorflow_and_ml():
    """Replace tensorflow and ml_model with lightweight stubs in sys.modules."""
    # Remove any previously cached (possibly broken) imports
    to_remove = [k for k in sys.modules if k == "tensorflow"
                 or k.startswith("tensorflow.")
                 or k == "ml_model"]
    for key in to_remove:
        del sys.modules[key]

    # Minimal tensorflow stub
    tf_stub = types.ModuleType("tensorflow")
    keras_stub = types.ModuleType("tensorflow.keras")
    tf_stub.keras = keras_stub
    sys.modules["tensorflow"] = tf_stub
    sys.modules["tensorflow.keras"] = keras_stub
    for sub in (
        "tensorflow.keras.models",
        "tensorflow.keras.layers",
        "tensorflow.keras.callbacks",
        "tensorflow.python",
        "tensorflow.python.tf2",
    ):
        sys.modules[sub] = types.ModuleType(sub)

    # Stub ml_model so analyst.py never triggers the real tensorflow import
    ml_stub = types.ModuleType("ml_model")
    ml_stub.run_ai_engine = lambda *a, **kw: {}
    ml_stub.train_model = lambda *a, **kw: {}
    ml_stub.classify_mode = lambda *a, **kw: ("Car", 80.0)
    sys.modules["ml_model"] = ml_stub


# Apply stubs immediately at import time (before any test fixture runs)
_stub_tensorflow_and_ml()

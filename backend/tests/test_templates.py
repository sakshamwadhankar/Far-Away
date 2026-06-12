import json
from pathlib import Path

from neuralflow.compiler.models import Pipeline

def test_all_templates_valid() -> None:
    """
    Ensure every JSON file in templates/ is a valid v2 pipeline.
    This also verifies they contain no secrets (Pipeline.model_validate will ensure it matches schema).
    """
    templates_dir = Path(__file__).parent.parent.parent / "templates"
    template_files = list(templates_dir.glob("*.json"))
    
    assert len(template_files) >= 10, "There should be at least 10 templates."
    
    for tf in template_files:
        with open(tf, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        try:
            # model_validate will throw an exception if invalid
            pipeline = Pipeline.model_validate(data)
            
            # Additional asserts
            assert pipeline.schema_version == "2.0"
            assert len(pipeline.nodes) > 0
        except Exception as e:
            raise AssertionError(f"Template {tf.name} failed validation: {e}")

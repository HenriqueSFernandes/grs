"""Tests for injector.scenario_loader."""

import tempfile

import pytest

from injector import scenario_loader


class TestValidation:
    """Parse-time validation rejects malformed scenarios."""

    def test_rejects_duplicate_step_ids(self):
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 1000
    faults:
      - loss: 10
  - id: s1
    type: fault
    target: c2
    duration: 1000
    faults:
      - latency: 200
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with pytest.raises(ValueError, match="duplicate"):
                scenario_loader.load(f.name)

    def test_rejects_missing_after_reference(self):
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 1000
    faults:
      - loss: 10
  - id: s2
    type: fault
    target: c2
    duration: 1000
    after: [nonexistent]
    faults:
      - latency: 200
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with pytest.raises(ValueError, match="after"):
                scenario_loader.load(f.name)

    def test_rejects_cycle(self):
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 1000
    after: [s2]
    faults:
      - loss: 10
  - id: s2
    type: fault
    target: c2
    duration: 1000
    after: [s1]
    faults:
      - latency: 200
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with pytest.raises(ValueError, match="cycle"):
                scenario_loader.load(f.name)

    def test_rejects_concurrent_same_target(self):
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 1000
    faults:
      - loss: 10
  - id: s2
    type: fault
    target: c1
    duration: 1000
    faults:
      - latency: 200
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with pytest.raises(ValueError, match="concurrent"):
                scenario_loader.load(f.name)

    def test_accepts_wait_steps(self):
        yaml = """
steps:
  - id: s1
    type: wait
    duration: 1000
  - id: s2
    type: fault
    target: c1
    duration: 500
    after: [s1]
    faults:
      - latency: 200
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            scenario = scenario_loader.load(f.name)

        assert scenario.steps[0].type == "wait"
        assert scenario.steps[0].target == ""
        assert scenario.steps[0].faults == []
        assert scenario.steps[1].after == ["s1"]

    def test_rejects_clear_in_faults(self):
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 1000
    faults:
      - clear: 0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with pytest.raises(ValueError, match="clear"):
                scenario_loader.load(f.name)

    def test_rejects_invalid_step_type(self):
        yaml = """
steps:
  - id: s1
    type: invalid
    duration: 1000
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with pytest.raises(ValueError, match="invalid type"):
                scenario_loader.load(f.name)

    def test_rejects_fault_without_target(self):
        yaml = """
steps:
  - id: s1
    type: fault
    duration: 1000
    faults:
      - loss: 10
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with pytest.raises(ValueError, match="target"):
                scenario_loader.load(f.name)

    def test_rejects_fault_without_faults(self):
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 1000
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with pytest.raises(ValueError, match="fault"):
                scenario_loader.load(f.name)

    def test_rejects_wait_with_target(self):
        yaml = """
steps:
  - id: s1
    type: wait
    duration: 1000
    target: c1
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with pytest.raises(ValueError, match="target"):
                scenario_loader.load(f.name)

    def test_rejects_wait_with_faults(self):
        yaml = """
steps:
  - id: s1
    type: wait
    duration: 1000
    faults:
      - loss: 10
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with pytest.raises(ValueError, match="fault"):
                scenario_loader.load(f.name)

    def test_rejects_negative_duration(self):
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: -1
    faults:
      - loss: 10
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with pytest.raises(ValueError, match="duration"):
                scenario_loader.load(f.name)

    def test_rejects_negative_delay(self):
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 1000
    delay: -1
    faults:
      - loss: 10
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with pytest.raises(ValueError, match="delay"):
                scenario_loader.load(f.name)

    def test_rejects_empty_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            with pytest.raises(ValueError, match="mapping"):
                scenario_loader.load(f.name)

    def test_rejects_steps_not_a_list(self):
        yaml = """
steps:
  id: s1
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with pytest.raises(ValueError, match="list"):
                scenario_loader.load(f.name)


class TestLoadValidScenario:
    """Happy-path parsing of well-formed scenario files."""

    def test_loads_minimal_scenario(self):
        yaml = """
name: "Minimal test"
steps:
  - id: s1
    type: fault
    target: victim
    duration: 5000
    faults:
      - latency: 500
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            scenario = scenario_loader.load(f.name)

        assert scenario.name == "Minimal test"
        assert len(scenario.steps) == 1
        assert scenario.steps[0].id == "s1"
        assert scenario.steps[0].type == "fault"
        assert scenario.steps[0].target == "victim"
        assert scenario.steps[0].duration == 5000
        assert scenario.steps[0].faults == [{"latency": 500}]
        assert scenario.steps[0].after == []
        assert scenario.steps[0].delay == 0

    def test_normalizes_string_after_to_list(self):
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 1000
    faults:
      - loss: 10
  - id: s2
    type: fault
    target: c2
    duration: 1000
    after: s1
    faults:
      - latency: 200
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            scenario = scenario_loader.load(f.name)

        assert scenario.steps[1].after == ["s1"]

    def test_preserves_list_after(self):
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 1000
    faults:
      - loss: 10
  - id: s2
    type: fault
    target: c2
    duration: 1000
    after: [s1]
    faults:
      - latency: 200
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            scenario = scenario_loader.load(f.name)

        assert scenario.steps[1].after == ["s1"]

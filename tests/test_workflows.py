import itertools
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path):
    # GitHub uses YAML 1.2; BaseLoader also keeps "on" and boolean inputs as strings.
    return yaml.load((ROOT / path).read_text(), Loader=yaml.BaseLoader)


def test_action_exposes_upstream_inputs_and_defaults():
    action = load_yaml("action.yml")

    assert {name: spec["default"] for name, spec in action["inputs"].items()} == {
        "android": "true",
        "dotnet": "true",
        "haskell": "true",
        "large-packages": "true",
        "docker-images": "true",
        "preinstalled-runtimes": "false",
        "tool-cache": "false",
        "swap-storage": "false",
    }
    assert "v3.0.0" in action["inputs"]["tool-cache"]["description"]


def test_action_passes_all_inputs_through_environment_not_shell_templates():
    action = load_yaml("action.yml")
    step, = [step for step in action["runs"]["steps"] if "free_disk_space.py" in step.get("run", "")]
    expected = {
        f"INPUT_{name.upper().replace('-', '_')}": "${{ inputs." + name + " }}"
        for name in action["inputs"]
    }

    assert {key: value for key, value in step["env"].items() if key.startswith("INPUT_")} == expected
    assert step["env"]["ACTION_PATH"] == "${{ github.action_path }}"
    assert 'python3 "$ACTION_PATH/free_disk_space.py"' in step["run"]
    assert 'python3 -m pip install -r "$ACTION_PATH/requirements.txt"' in step["run"]
    for action_step in action["runs"]["steps"]:
        assert "${{" not in action_step.get("run", "")


def test_hourly_matrix_covers_every_distinct_cleanup_configuration():
    action = load_yaml("action.yml")
    workflow = load_yaml(".github/workflows/test-all-combinations.yml")
    job, = workflow["jobs"].values()
    matrix = job["strategy"]["matrix"]
    names = set(action["inputs"]) - {"tool-cache"}

    assert set(matrix) == names
    assert all(set(values) == {"true", "false"} and len(values) == 2 for values in matrix.values())
    combinations = set(itertools.product(*matrix.values()))
    assert len(combinations) == 128
    assert ("false",) * len(names) in combinations
    assert ("true",) * len(names) in combinations
    assert job["strategy"]["fail-fast"] == "false"
    assert workflow["on"]["schedule"] == [{"cron": "15 * * * *"}]
    assert workflow["env"]["SENTRY_DSN"] == "${{ secrets.SENTRY_DSN }}"
    step, = [step for step in job["steps"] if step.get("uses") == "./"]
    assert step["with"] == {
        **{name: "${{ matrix." + name + " }}" for name in names},
        "tool-cache": "false",
    }
    for combination in combinations:
        values = dict(zip(matrix, combination))
        rendered_name = job["name"]
        for name, value in values.items():
            rendered_name = rendered_name.replace("${{ matrix." + name + " }}", value)
        configured_inputs = {**values, "tool-cache": "false"}
        assert rendered_name == "; ".join(
            f"{name}: {configured_inputs[name]}" for name in step["with"]
        )


def test_workflows_run_checked_out_action_and_only_supported_inputs():
    action = load_yaml("action.yml")
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow = load_yaml(path)
        for job in workflow["jobs"].values():
            for index, step in enumerate(job["steps"]):
                uses = step.get("uses", "")
                assert not uses.startswith("ChrisCarini/free-disk-space@")
                if uses == "./":
                    assert set(step.get("with", {})) <= set(action["inputs"])
                    assert any(
                        previous.get("uses", "").startswith("actions/checkout@")
                        for previous in job["steps"][:index]
                    )


def test_push_and_pull_requests_run_regressions_before_live_cleanup():
    workflow = load_yaml(".github/workflows/test.yml")

    assert {"push", "pull_request"} <= set(workflow["on"])
    assert workflow["jobs"]["free-disk-space"]["needs"] == "unit-tests"
    assert any(
        step.get("run") == "python -m pytest -q"
        for step in workflow["jobs"]["unit-tests"]["steps"]
    )
    step, = [
        step for step in workflow["jobs"]["free-disk-space"]["steps"]
        if step.get("uses") == "./"
    ]
    assert step["env"]["SENTRY_DSN"] == "${{ secrets.SENTRY_DSN }}"
    assert set(step["with"]) == set(load_yaml("action.yml")["inputs"]) - {"tool-cache"}
    assert all(value == "true" for value in step["with"].values())

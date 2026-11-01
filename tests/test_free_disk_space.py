import importlib
import itertools
import subprocess
from unittest.mock import Mock

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport


INPUT_DEFAULTS = {
    "android": True,
    "dotnet": True,
    "haskell": True,
    "large-packages": True,
    "docker-images": True,
    "preinstalled-runtimes": False,
    "tool-cache": False,
    "swap-storage": False,
}
CANONICAL_INPUTS = tuple(name for name in INPUT_DEFAULTS if name != "tool-cache")
GENERAL_APT_COMMANDS = [
    ["sudo", "apt-get", "remove", "-y", "^llvm-.*", "--fix-missing"],
    ["sudo", "apt-get", "remove", "-y", "php.*", "--fix-missing"],
    ["sudo", "apt-get", "remove", "-y", "^mongodb-.*", "--fix-missing"],
    ["sudo", "apt-get", "remove", "-y", "^mysql-.*", "--fix-missing"],
    ["sudo", "apt-get", "remove", "-y", "azure-cli", "google-chrome-stable", "firefox",
     "powershell", "mono-devel", "libgl1-mesa-dri", "--fix-missing"],
    ["sudo", "apt-get", "remove", "-y", "google-cloud-sdk", "--fix-missing"],
    ["sudo", "apt-get", "remove", "-y", "google-cloud-cli", "--fix-missing"],
    ["sudo", "apt-get", "autoremove", "-y"],
    ["sudo", "apt-get", "clean"],
]
RUNTIME_COMMAND = ["sudo", "rm", "-rf", "/opt/hostedtoolcache"]


class MemoryTransport(Transport):
    def __init__(self):
        super().__init__()
        self.envelopes = []

    def capture_envelope(self, envelope):
        self.envelopes.append(envelope)

    def events(self, event_type):
        return [
            item.payload.json
            for envelope in self.envelopes
            for item in envelope.items
            if item.headers["type"] == event_type
        ]


class FakeCommands:
    def __init__(self):
        self.cleanup_commands = []
        self.available_kb = 1000
        self.failing_command = None

    def run(self, command, **kwargs):
        assert isinstance(command, list)
        assert not kwargs.get("shell", False)
        if command[0] == "df":
            return subprocess.CompletedProcess(
                command, 0,
                stdout=f"Filesystem 1K-blocks Used Available Use% Mounted on\n"
                       f"/dev/root 100000 1000 {self.available_kb} 1% /\n",
            )
        if command[0] == "numfmt":
            return subprocess.CompletedProcess(command, 0, stdout=f"{command[-1]}B\n")
        if command[0] in ("sudo", "free"):
            self.cleanup_commands.append(command)
            if command == self.failing_command:
                raise subprocess.CalledProcessError(1, command, stderr="Simulated command failure")
            if command[0] == "sudo":
                self.available_kb += 100
            return subprocess.CompletedProcess(command, 0)
        raise AssertionError(f"Unexpected command: {command}")


@pytest.fixture(autouse=True)
def commands(monkeypatch):
    runner = FakeCommands()
    monkeypatch.setattr(subprocess, "run", runner.run)
    return runner


@pytest.fixture
def cleanup(monkeypatch):
    for name in INPUT_DEFAULTS:
        monkeypatch.delenv(f"INPUT_{name.upper().replace('-', '_')}", raising=False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("AGENT_TOOLSDIRECTORY", "/opt/hostedtoolcache")
    return importlib.reload(importlib.import_module("free_disk_space"))


@pytest.fixture
def telemetry():
    transport = MemoryTransport()
    client = sentry_sdk.Client(
        dsn="https://public@example.invalid/1",
        transport=transport,
        traces_sample_rate=1.0,
        default_integrations=False,
        auto_enabling_integrations=False,
    )
    try:
        with sentry_sdk.isolation_scope() as scope:
            scope.set_client(client)
            yield transport
    finally:
        client.close()


def configure(cleanup, monkeypatch, **enabled):
    for name in INPUT_DEFAULTS:
        monkeypatch.setenv(
            f"INPUT_{name.upper().replace('-', '_')}",
            str(enabled.get(name, False)).lower(),
        )
    importlib.reload(cleanup)


def test_input_defaults_preserve_swap_and_preinstalled_runtimes(cleanup):
    assert cleanup.get_inputs() == INPUT_DEFAULTS


def test_import_does_not_print_or_run_cleanup(cleanup, commands, capsys):
    importlib.reload(cleanup)

    assert commands.cleanup_commands == []
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("name", INPUT_DEFAULTS)
@pytest.mark.parametrize(
    "value, expected",
    [("true", True), ("TRUE", True), ("TrUe", True), ("false", False), ("FALSE", False),
     ("", False), ("1", False), ("true; printf INJECTED", False), ("$(printf true)", False)],
)
def test_inputs_are_parsed_as_data(cleanup, monkeypatch, name, value, expected):
    monkeypatch.setenv(f"INPUT_{name.upper().replace('-', '_')}", value)

    importlib.reload(cleanup)

    assert cleanup.get_inputs()[name] is expected


@pytest.mark.parametrize("values", list(itertools.product((False, True), repeat=len(CANONICAL_INPUTS))))
def test_all_canonical_combinations_preserve_commands_and_instrumentation(
        cleanup, monkeypatch, commands, telemetry, capsys, values):
    options = dict(zip(CANONICAL_INPUTS, values))
    configure(cleanup, monkeypatch, **options)

    cleanup.main()

    expected = []
    if options["android"]:
        expected.append(["sudo", "rm", "-rf", "/usr/local/lib/android"])
    if options["dotnet"]:
        expected.append(["sudo", "rm", "-rf", "/usr/share/dotnet"])
    if options["haskell"]:
        expected.extend([
            ["sudo", "rm", "-rf", "/opt/ghc"],
            ["sudo", "rm", "-rf", "/usr/local/.ghcup"],
        ])
    if options["large-packages"]:
        if options["dotnet"]:
            expected.extend([
                ["sudo", "apt-get", "remove", "-y", "^aspnetcore-.*"],
                ["sudo", "apt-get", "remove", "-y", "^dotnet-.*", "--fix-missing"],
            ])
        expected.extend(GENERAL_APT_COMMANDS)
    if options["docker-images"]:
        expected.append(["sudo", "docker", "image", "prune", "--all", "--force"])
    if options["preinstalled-runtimes"]:
        expected.append(RUNTIME_COMMAND)
    if options["swap-storage"]:
        expected.extend([
            ["sudo", "swapoff", "-a"],
            ["sudo", "rm", "-f", "/mnt/swapfile"],
            ["free", "-h"],
        ])
    assert commands.cleanup_commands == expected

    transaction, = telemetry.events("transaction")
    for name, value in {**options, "tool-cache": False}.items():
        assert transaction["tags"][f"input.{name}"] == str(value).lower()
    assert transaction["tags"]["cleanup.preinstalled_runtimes"] == str(
        options["preinstalled-runtimes"]
    ).lower()
    assert transaction["contexts"]["trace"]["data"]["total_kb_freed"] == commands.available_kb - 1000

    spans = {span["op"]: span for span in transaction["spans"]}
    for name, op in {
        "android": "cleanup.android",
        "dotnet": "cleanup.dotnet",
        "haskell": "cleanup.haskell",
        "large-packages": "cleanup.packages",
        "docker-images": "cleanup.docker",
        "preinstalled-runtimes": "cleanup.toolcache",
        "swap-storage": "cleanup.swap",
    }.items():
        assert (op in spans) is options[name]
        if options[name]:
            assert spans[op]["data"]["saved_kb"] > 0
            assert "saved_formatted" in spans[op]["data"]
    if options["large-packages"]:
        assert spans["cleanup.packages"]["data"]["dotnet_exempted"] is not options["dotnet"]

    output = capsys.readouterr().out
    assert ("::notice::dotnet: false" in output) is (
        options["large-packages"] and not options["dotnet"]
    )
    assert "deprecated" not in output


@pytest.mark.parametrize(
    "preinstalled_runtimes, tool_cache",
    [(False, False), (False, True), (True, False), (True, True)],
)
def test_runtime_alias_uses_or_semantics_warns_and_records_once(
        cleanup, monkeypatch, commands, telemetry, capsys, preinstalled_runtimes, tool_cache):
    configure(cleanup, monkeypatch, **{
        "preinstalled-runtimes": preinstalled_runtimes,
        "tool-cache": tool_cache,
    })

    cleanup.main()

    enabled = preinstalled_runtimes or tool_cache
    assert commands.cleanup_commands == ([RUNTIME_COMMAND] if enabled else [])
    output = capsys.readouterr().out
    assert ("::warning::The 'tool-cache' input is deprecated" in output) is tool_cache
    assert ("until v3.0.0" in output) is tool_cache
    transaction, = telemetry.events("transaction")
    assert transaction["tags"]["input.preinstalled-runtimes"] == str(preinstalled_runtimes).lower()
    assert transaction["tags"]["input.tool-cache"] == str(tool_cache).lower()
    assert transaction["tags"]["cleanup.preinstalled_runtimes"] == str(enabled).lower()
    runtime_spans = [span for span in transaction["spans"] if span["op"] == "cleanup.toolcache"]
    assert len(runtime_spans) == int(enabled)
    if enabled:
        span, = runtime_spans
        assert span["description"] == "Remove Pre-installed runtimes"
        assert span["data"]["deprecated_alias_used"] is tool_cache
        assert span["data"]["agent_tools_dir"] == "/opt/hostedtoolcache"
        assert span["data"]["saved_kb"] == 100


@pytest.mark.parametrize("input_name", ["preinstalled-runtimes", "tool-cache"])
@pytest.mark.parametrize("directory", [None, ""])
def test_missing_tool_directory_is_reported_without_running_rm(
        cleanup, monkeypatch, commands, telemetry, capsys, input_name, directory):
    configure(cleanup, monkeypatch, **{input_name: True})
    if directory is None:
        monkeypatch.delenv("AGENT_TOOLSDIRECTORY")
    else:
        monkeypatch.setenv("AGENT_TOOLSDIRECTORY", directory)

    cleanup.main()

    assert commands.cleanup_commands == []
    assert "::warning::AGENT_TOOLSDIRECTORY is not set" in capsys.readouterr().out
    transaction, = telemetry.events("transaction")
    span, = [span for span in transaction["spans"] if span["op"] == "cleanup.toolcache"]
    assert span["data"]["skipped"] is True
    assert span["data"]["saved_kb"] == 0


def test_tool_directory_with_spaces_is_passed_as_one_argument(cleanup, monkeypatch, commands):
    configure(cleanup, monkeypatch, **{"preinstalled-runtimes": True})
    monkeypatch.setenv("AGENT_TOOLSDIRECTORY", "/opt/hosted toolcache")

    cleanup.main()

    assert commands.cleanup_commands == [["sudo", "rm", "-rf", "/opt/hosted toolcache"]]


def test_package_failure_is_captured_and_remaining_cleanup_continues(
        cleanup, monkeypatch, commands, telemetry, capsys):
    configure(cleanup, monkeypatch, **{"large-packages": True, "docker-images": True})
    monkeypatch.setattr(cleanup, "SENTRY_DSN", "configured")
    commands.failing_command = GENERAL_APT_COMMANDS[0]

    cleanup.main()

    assert commands.cleanup_commands == [
        *GENERAL_APT_COMMANDS,
        ["sudo", "docker", "image", "prune", "--all", "--force"],
    ]
    assert "::warning::The command [sudo apt-get remove -y ^llvm-.*" in capsys.readouterr().out
    event, = telemetry.events("event")
    assert event["exception"]["values"][0]["type"] == "CalledProcessError"
    assert event["extra"]["command"] == " ".join(commands.failing_command)
    assert event["extra"]["returncode"] == 1
    transaction, = telemetry.events("transaction")
    failed_span, = [
        span for span in transaction["spans"]
        if span["op"] == "command" and span["data"]["command"] == " ".join(commands.failing_command)
    ]
    assert failed_span["status"] == "internal_error"
    package_span, = [
        span for span in transaction["spans"]
        if span["op"] == "cleanup.packages.cmd" and span["data"]["command"] == " ".join(commands.failing_command)
    ]
    assert package_span["data"]["success"] is False
    assert package_span["data"]["saved_kb"] == 0


def test_sentry_initialization_preserves_github_context(cleanup, monkeypatch):
    initialize = Mock()
    set_tag = Mock()
    monkeypatch.setattr(sentry_sdk, "init", initialize)
    monkeypatch.setattr(sentry_sdk, "set_tag", set_tag)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("GITHUB_ENVIRONMENT", "testing")
    monkeypatch.setenv("GITHUB_SHA", "test-sha")
    for key, value in {
        "GITHUB_REPOSITORY": "example/action",
        "GITHUB_WORKFLOW": "Test All Combinations",
        "GITHUB_RUN_ID": "123",
        "GITHUB_JOB": "free-disk-space",
    }.items():
        monkeypatch.setenv(key, value)

    importlib.reload(cleanup)

    initialize.assert_called_once_with(
        dsn="https://public@example.invalid/1",
        traces_sample_rate=1.0,
        environment="testing",
        release="test-sha",
    )
    assert {call.args for call in set_tag.call_args_list} == {
        ("github.repository", "example/action"),
        ("github.workflow", "Test All Combinations"),
        ("github.run_id", "123"),
        ("github.job_id", "free-disk-space"),
    }


def test_sentry_initialization_is_optional(cleanup, monkeypatch):
    initialize = Mock()
    monkeypatch.setattr(sentry_sdk, "init", initialize)

    importlib.reload(cleanup)

    initialize.assert_not_called()

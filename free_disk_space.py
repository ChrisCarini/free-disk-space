#!/usr/bin/env python3
import builtins
import os
import subprocess
from contextlib import contextmanager
from functools import partial
from typing import Generator

import sentry_sdk
from sentry_sdk import capture_exception, set_tag
from sentry_sdk.tracing import Span

# Force immediate flushing of all print statements
print = partial(builtins.print, flush=True)

ANDROID = os.environ.get("INPUT_ANDROID", "true").lower() == "true"
DOCKER_IMAGES = os.environ.get("INPUT_DOCKER_IMAGES", "true").lower() == "true"
DOTNET = os.environ.get("INPUT_DOTNET", "true").lower() == "true"
HASKELL = os.environ.get("INPUT_HASKELL", "true").lower() == "true"
LARGE_PACKAGES = os.environ.get("INPUT_LARGE_PACKAGES", "true").lower() == "true"
PREINSTALLED_RUNTIMES = os.environ.get("INPUT_PREINSTALLED_RUNTIMES", "false").lower() == "true"
SWAP_STORAGE = os.environ.get("INPUT_SWAP_STORAGE", "false").lower() == "true"
TOOL_CACHE = os.environ.get("INPUT_TOOL_CACHE", "false").lower() == "true"


def get_inputs() -> dict[str, bool]:
    return {
        "android": ANDROID,
        "dotnet": DOTNET,
        "haskell": HASKELL,
        "large-packages": LARGE_PACKAGES,
        "docker-images": DOCKER_IMAGES,
        "preinstalled-runtimes": PREINSTALLED_RUNTIMES,
        "tool-cache": TOOL_CACHE,
        "swap-storage": SWAP_STORAGE,
    }


def print_inputs():
    print("==== CONFIGURED OPTIONS ====")
    for key, value in get_inputs().items():
        print(f"  {key}: {value}")
    print("===========================")
    print()


# Initialize Sentry SDK
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=1.0,  # Capture 100% of transactions for performance monitoring
        environment=os.environ.get("GITHUB_ENVIRONMENT", "production"),
        release=os.environ.get("GITHUB_SHA", "unknown"),
    )
    # Add GitHub context to Sentry events
    set_tag("github.repository", os.environ.get("GITHUB_REPOSITORY", "unknown"))
    set_tag("github.workflow", os.environ.get("GITHUB_WORKFLOW", "unknown"))
    set_tag("github.run_id", os.environ.get("GITHUB_RUN_ID", "unknown"))
    set_tag("github.job_id", os.environ.get("GITHUB_JOB", "unknown"))


# ======
# UTILITY FUNCTIONS
# ======

def print_separation_line(char="=", num=80):
    """Print a line of characters for visual separation"""
    print(char * num)


def get_available_space(path: str = None) -> int:
    """Get available space in KB"""
    cmd = ["df", "-a"]
    if path:
        cmd.append(path)

    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = result.stdout.strip().split('\n')[1:]  # Skip header

    total_avail = 0
    for line in lines:
        parts = line.split()
        if len(parts) >= 4:
            try:
                total_avail += int(parts[3])
            except ValueError:
                pass

    return total_avail


def format_byte_count(kb: int):
    """Format KB to human-readable format"""
    cmd = ["numfmt", "--to=iec-i", "--suffix=B", "--padding=7", f"{kb}000"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    formatted = result.stdout.strip()
    return formatted


def print_saved_space(saved: int, title: str = None):
    """Print how much space was saved"""
    print()
    print_separation_line("*", 80)
    if title:
        print(f"=> {title}: Saved {format_byte_count(saved)}")
    else:
        print(f"=> Saved {format_byte_count(saved)}")
    print_separation_line("*", 80)
    print()


def print_dh(caption: str = None) -> None:
    """Print disk usage with caption"""
    print_separation_line("=", 80)
    if caption:
        print(caption)
        print()

    print("$ df -h /")
    print()
    subprocess.run(["df", "-h", "/"], check=False)

    print("$ df -a /")
    print()
    subprocess.run(["df", "-a", "/"], check=False)

    print("$ df -a")
    print()
    subprocess.run(["df", "-a"], check=False)

    print_separation_line("=", 80)


@contextmanager
def recording(remove: str, op: str) -> Generator[Span, None, None]:
    with sentry_sdk.start_span(description=f'Remove {remove}', op=op) as span:
        before = get_available_space()

        yield span

        after = get_available_space()
        saved = after - before
        span.set_data("saved_kb", saved)
        span.set_data("saved_formatted", format_byte_count(saved))
        print_saved_space(saved, title=remove)


def run_command(cmd: list[str], error_msg: str = None):
    """Run a shell command and handle errors gracefully"""
    full_command = ' '.join(cmd)
    try:
        with sentry_sdk.start_span(description=f"Command: {full_command}", op="command") as span:
            span.set_data("command", full_command)
            result = subprocess.run(cmd, check=True)
            span.set_data("status", "success")
            return True
    except subprocess.CalledProcessError as e:
        if error_msg:
            print(f"::warning::{error_msg}")
        if SENTRY_DSN:
            with sentry_sdk.push_scope() as scope:
                scope.set_extra("command", full_command)
                scope.set_extra("returncode", e.returncode)
                scope.set_extra("stderr", e.stderr if hasattr(e, 'stderr') else None)
                capture_exception(e)
        return False


def main():
    # Start a transaction to monitor the entire cleanup process
    with sentry_sdk.start_transaction(op="cleanup", name="Disk Space Cleanup") as transaction:
        for name, value in get_inputs().items():
            transaction.set_tag(f"input.{name}", str(value).lower())
        remove_preinstalled_runtimes = PREINSTALLED_RUNTIMES or TOOL_CACHE
        transaction.set_tag("cleanup.preinstalled_runtimes", str(remove_preinstalled_runtimes).lower())
        print_inputs()

        # Display initial disk space stats
        with sentry_sdk.start_span(description="Initial space measurement", op="cleanup.init") as span:
            available_initial = get_available_space()
            available_root_initial = get_available_space('/')
            span.set_data("initial_kb", available_initial)
            span.set_data("initial_root_kb", available_root_initial)

            print_dh("BEFORE CLEAN-UP:")
            print()

        # Option: Remove Android library
        if ANDROID:
            with recording(remove="Android library", op="cleanup.android"):
                run_command(["sudo", "rm", "-rf", "/usr/local/lib/android"])

        # Option: Remove .NET runtime
        if DOTNET:
            with recording(remove=".NET runtime", op="cleanup.dotnet"):
                run_command(["sudo", "rm", "-rf", "/usr/share/dotnet"])

        # Option: Remove Haskell runtime
        if HASKELL:
            with recording(remove="Haskell runtime", op="cleanup.haskell"):
                run_command(["sudo", "rm", "-rf", "/opt/ghc"])
                run_command(["sudo", "rm", "-rf", "/usr/local/.ghcup"])

        # Option: Remove large packages
        if LARGE_PACKAGES:
            with recording(remove="Large packages", op="cleanup.packages") as span:
                span.set_data("dotnet_exempted", not DOTNET)
                apt_commands = []
                if DOTNET:
                    apt_commands.extend([
                        ["sudo", "apt-get", "remove", "-y", "^aspnetcore-.*"],
                        ["sudo", "apt-get", "remove", "-y", "^dotnet-.*", "--fix-missing"],
                    ])
                else:
                    print("::notice::dotnet: false - .NET packages exempted from large-packages "
                          "(dotnet-*, aspnetcore-*).")

                apt_commands.extend([
                    ["sudo", "apt-get", "remove", "-y", "^llvm-.*", "--fix-missing"],
                    ["sudo", "apt-get", "remove", "-y", "php.*", "--fix-missing"],
                    ["sudo", "apt-get", "remove", "-y", "^mongodb-.*", "--fix-missing"],
                    ["sudo", "apt-get", "remove", "-y", "^mysql-.*", "--fix-missing"],
                    ["sudo", "apt-get", "remove", "-y", "azure-cli", "google-chrome-stable", "firefox", "powershell",
                     "mono-devel", "libgl1-mesa-dri", "--fix-missing"],
                    ["sudo", "apt-get", "remove", "-y", "google-cloud-sdk", "--fix-missing"],
                    ["sudo", "apt-get", "remove", "-y", "google-cloud-cli", "--fix-missing"],
                    ["sudo", "apt-get", "autoremove", "-y"],
                    ["sudo", "apt-get", "clean"]
                ])

                for i, cmd in enumerate(apt_commands):
                    full_command = ' '.join(cmd)
                    with recording(remove=f"Large Package: {full_command.removeprefix('sudo apt-get ')}",
                                   op="cleanup.packages.cmd") as cmd_span:
                        cmd_span.set_data("command", full_command)
                        error_msg = f"The command [{full_command}] failed to complete successfully. Proceeding..."
                        success = run_command(cmd, error_msg)
                        cmd_span.set_data("success", success)

        # Option: Remove Docker images
        if DOCKER_IMAGES:
            with recording(remove="Docker images", op="cleanup.docker"):
                run_command(["sudo", "docker", "image", "prune", "--all", "--force"])

        if TOOL_CACHE:
            print("::warning::The 'tool-cache' input is deprecated; it was renamed to "
                  "'preinstalled-runtimes'. It still works and will keep working until v3.0.0 - "
                  "please rename it when convenient.")

        # Keep the span operation stable for existing Sentry dashboards.
        if remove_preinstalled_runtimes:
            with recording(remove="Pre-installed runtimes", op="cleanup.toolcache") as span:
                span.set_data("deprecated_alias_used", TOOL_CACHE)
                agent_tools_dir = os.environ.get("AGENT_TOOLSDIRECTORY", "")
                span.set_data("agent_tools_dir", agent_tools_dir)
                if agent_tools_dir:
                    run_command(["sudo", "rm", "-rf", agent_tools_dir])
                else:
                    span.set_data("skipped", True)
                    print("::warning::AGENT_TOOLSDIRECTORY is not set; "
                          "skipping pre-installed runtimes cleanup.")

        # Option: Remove Swap storage
        if SWAP_STORAGE:
            with recording(remove="Swap storage", op="cleanup.swap"):
                run_command(["sudo", "swapoff", "-a"])
                run_command(["sudo", "rm", "-f", "/mnt/swapfile"])
                run_command(["free", "-h"])

        # Output saved space statistic
        with sentry_sdk.start_span(description="Calculate final statistics", op="cleanup.stats") as span:
            available_end = get_available_space()
            available_root_end = get_available_space('/')

            root_saved = available_root_end - available_root_initial
            total_saved = available_end - available_initial

            span.set_data("initial_kb", available_initial)
            span.set_data("final_kb", available_end)
            span.set_data("total_saved_kb", total_saved)
            span.set_data("total_saved_formatted", format_byte_count(total_saved))

            print()
            print_dh("AFTER CLEAN-UP:")
            print()
            print()

            print("/dev/root:")
            print_saved_space(root_saved)
            print("overall:")
            print_saved_space(total_saved)

            print_inputs()

        # Set the status and metrics on the transaction
        transaction.set_tag("cleanup.success", "true")
        transaction.set_data("total_kb_freed", total_saved)
        transaction.set_data("total_freed_formatted", format_byte_count(total_saved))


if __name__ == "__main__":
    try:
        with sentry_sdk.start_span(description="Main execution", op="script.main"):
            main()
    except Exception as e:
        if SENTRY_DSN:
            sentry_sdk.capture_exception(e)
        raise

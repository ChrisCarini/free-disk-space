#!/usr/bin/env python3
import os
import subprocess
import re
import sentry_sdk
from sentry_sdk import capture_exception, set_tag, start_transaction

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

# ======
# UTILITY FUNCTIONS
# ======

def print_separation_line(char="=", num=80):
    """Print a line of characters for visual separation"""
    print(char * num)

def get_available_space(path=None):
    """Get available space in KB"""
    with sentry_sdk.start_span(description=f"Get available space: {path if path else 'all'}", op="disk.space") as span:
        cmd = ["df", "-a"]
        if path:
            cmd.append(path)
            span.set_data("path", path)

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

        span.set_data("available_kb", total_avail)
        return total_avail

def format_byte_count(kb):
    """Format KB to human-readable format"""
    with sentry_sdk.start_span(description="Format byte count", op="utility.format") as span:
        span.set_data("kb_input", kb)
        cmd = ["numfmt", "--to=iec-i", "--suffix=B", "--padding=7", f"{kb}000"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        formatted = result.stdout.strip()
        span.set_data("formatted_output", formatted)
        return formatted

def print_saved_space(saved, title=None):
    """Print how much space was saved"""
    with sentry_sdk.start_span(description="Print saved space", op="utility.report") as span:
        if title:
            span.set_data("title", title)
        span.set_data("saved_kb", saved)

        print()
        print_separation_line("*", 80)
        if title:
            print(f"=> {title}: Saved {format_byte_count(saved)}")
        else:
            print(f"=> Saved {format_byte_count(saved)}")
        print_separation_line("*", 80)
        print()

def print_dh(caption=None):
    """Print disk usage with caption"""
    with sentry_sdk.start_span(description="Print disk usage", op="disk.report") as span:
        if caption:
            span.set_data("caption", caption)

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

def run_command(cmd, error_msg=None):
    """Run a shell command and handle errors gracefully"""
    try:
        with sentry_sdk.start_span(description=f"Command: {' '.join(cmd)}", op="command") as span:
            span.set_data("command", ' '.join(cmd))
            result = subprocess.run(cmd, check=True)
            span.set_data("status", "success")
            return True
    except subprocess.CalledProcessError as e:
        if error_msg:
            print(f"::warning::{error_msg}")
        if SENTRY_DSN:
            with sentry_sdk.push_scope() as scope:
                scope.set_extra("command", ' '.join(cmd))
                scope.set_extra("returncode", e.returncode)
                scope.set_extra("stderr", e.stderr if hasattr(e, 'stderr') else None)
                capture_exception(e)
        return False

def get_input(name, default="false"):
    """Get input parameter from environment variable"""
    var_name = f"INPUT_{name.replace('-', '_').upper()}"
    return os.environ.get(var_name, default).lower() == "true"

def main():
    # Start a transaction to monitor the entire cleanup process
    with sentry_sdk.start_transaction(op="cleanup", name="Disk Space Cleanup") as transaction:
        # Display initial disk space stats
        with sentry_sdk.start_span(description="Initial space measurement", op="cleanup.init") as span:
            available_initial = get_available_space()
            available_root_initial = get_available_space('/')
            span.set_data("initial_kb", available_initial)
            span.set_data("initial_root_kb", available_root_initial)

            print_dh("BEFORE CLEAN-UP:")
            print()

        # Option: Remove Android library
        if get_input("android", "true"):
            with sentry_sdk.start_span(description="Remove Android library", op="cleanup.android") as span:
                before = get_available_space()
                run_command(["sudo", "rm", "-rf", "/usr/local/lib/android"])
                after = get_available_space()
                saved = after - before
                span.set_data("saved_kb", saved)
                span.set_data("saved_formatted", format_byte_count(saved))
                print_saved_space(saved, "Android library")

        # Option: Remove .NET runtime
        if get_input("dotnet", "true"):
            with sentry_sdk.start_span(description="Remove .NET runtime", op="cleanup.dotnet") as span:
                before = get_available_space()
                run_command(["sudo", "rm", "-rf", "/usr/share/dotnet"])
                after = get_available_space()
                saved = after - before
                span.set_data("saved_kb", saved)
                span.set_data("saved_formatted", format_byte_count(saved))
                print_saved_space(saved, ".NET runtime")

        # Option: Remove Haskell runtime
        if get_input("haskell", "true"):
            with sentry_sdk.start_span(description="Remove Haskell runtime", op="cleanup.haskell") as span:
                before = get_available_space()
                run_command(["sudo", "rm", "-rf", "/opt/ghc"])
                run_command(["sudo", "rm", "-rf", "/usr/local/.ghcup"])
                after = get_available_space()
                saved = after - before
                span.set_data("saved_kb", saved)
                span.set_data("saved_formatted", format_byte_count(saved))
                print_saved_space(saved, "Haskell runtime")

        # Option: Remove large packages
        if get_input("large-packages", "true"):
            with sentry_sdk.start_span(description="Remove large packages", op="cleanup.packages") as span:
                before = get_available_space()

                # Execute all the apt-get commands
                apt_commands = [
                    ["sudo", "apt-get", "remove", "-y", "^aspnetcore-.*"],
                    ["sudo", "apt-get", "remove", "-y", "^dotnet-.*", "--fix-missing"],
                    ["sudo", "apt-get", "remove", "-y", "^llvm-.*", "--fix-missing"],
                    ["sudo", "apt-get", "remove", "-y", "php.*", "--fix-missing"],
                    ["sudo", "apt-get", "remove", "-y", "^mongodb-.*", "--fix-missing"],
                    ["sudo", "apt-get", "remove", "-y", "^mysql-.*", "--fix-missing"],
                    ["sudo", "apt-get", "remove", "-y", "azure-cli", "google-chrome-stable", "firefox", "powershell", "mono-devel", "libgl1-mesa-dri", "--fix-missing"],
                    ["sudo", "apt-get", "remove", "-y", "google-cloud-sdk", "--fix-missing"],
                    ["sudo", "apt-get", "remove", "-y", "google-cloud-cli", "--fix-missing"],
                    ["sudo", "apt-get", "autoremove", "-y"],
                    ["sudo", "apt-get", "clean"]
                ]

                for i, cmd in enumerate(apt_commands):
                    with sentry_sdk.start_span(description=f"Package removal {i+1}/{len(apt_commands)}", op="cleanup.packages.cmd") as cmd_span:
                        cmd_span.set_data("command", ' '.join(cmd))
                        error_msg = f"The command [{' '.join(cmd)}] failed to complete successfully. Proceeding..."
                        success = run_command(cmd, error_msg)
                        cmd_span.set_data("success", success)

                after = get_available_space()
                saved = after - before
                span.set_data("saved_kb", saved)
                span.set_data("saved_formatted", format_byte_count(saved))
                print_saved_space(saved, "Large misc. packages")

        # Option: Remove Docker images
        if get_input("docker-images", "true"):
            with sentry_sdk.start_span(description="Remove Docker images", op="cleanup.docker") as span:
                before = get_available_space()
                run_command(["sudo", "docker", "image", "prune", "--all", "--force"])
                after = get_available_space()
                saved = after - before
                span.set_data("saved_kb", saved)
                span.set_data("saved_formatted", format_byte_count(saved))
                print_saved_space(saved, "Docker images")

        # Option: Remove tool cache
        if get_input("tool-cache", "false"):
            with sentry_sdk.start_span(description="Remove tool cache", op="cleanup.toolcache") as span:
                before = get_available_space()
                agent_tools_dir = os.environ.get("AGENT_TOOLSDIRECTORY", "")
                if agent_tools_dir:
                    span.set_data("agent_tools_dir", agent_tools_dir)
                    run_command(["sudo", "rm", "-rf", agent_tools_dir])
                after = get_available_space()
                saved = after - before
                span.set_data("saved_kb", saved)
                span.set_data("saved_formatted", format_byte_count(saved))
                print_saved_space(saved, "Tool cache")

        # Option: Remove Swap storage
        if get_input("swap-storage", "true"):
            with sentry_sdk.start_span(description="Remove swap storage", op="cleanup.swap") as span:
                before = get_available_space()
                run_command(["sudo", "swapoff", "-a"])
                run_command(["sudo", "rm", "-f", "/mnt/swapfile"])
                run_command(["free", "-h"])
                after = get_available_space()
                saved = after - before
                span.set_data("saved_kb", saved)
                span.set_data("saved_formatted", format_byte_count(saved))
                print_saved_space(saved, "Swap storage")

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

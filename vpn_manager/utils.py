"""Utility functions for VPN Manager."""

import functools
import json
import os
import subprocess
import sys
from typing import Tuple, Any, Optional
from yaspin import yaspin
from yaspin.spinners import Spinners


class Colors:
    """ANSI color codes for colored terminal output."""
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


def print_color(message: str, color: str, end: str = "\n") -> None:
    """Print a message in color to the terminal."""
    print(f"{color}{message}{Colors.ENDC}", end=end)


def print_info(message: str) -> None:
    """Print an informational message in blue."""
    print_color(message, Colors.BLUE)


def print_success(message: str) -> None:
    """Print a success message in green."""
    print_color(message, Colors.GREEN)


def print_warning(message: str) -> None:
    """Print a warning message in yellow."""
    print_color(message, Colors.YELLOW)


def print_error(message: str) -> None:
    """Print an error message in red."""
    print_color(message, Colors.RED)


def get_public_ip_info(ip_info_service: str) -> Optional[dict]:
    """Fetches the public IP address and country from a public IP checking service."""
    try:
        response = subprocess.run(f"curl -s {ip_info_service}", shell=True,
                                 text=True, capture_output=True, check=True)
        return json.loads(response.stdout)
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to retrieve public IP information: {e.stderr}")
        return None
    except json.JSONDecodeError:
        print_error("Failed to parse IP information response.")
        return None


def run_command(command: str, check: bool = True, capture_output: bool = True, silent: bool = False, verbose: bool = False) -> Tuple[bool, Any]:
    """
    Wrapper for subprocess.run with error handling.
    
    Args:
        command: The command to run
        check: Whether to check the return code
        capture_output: Whether to capture stdout/stderr
        silent: Whether to suppress command output and error messages to console
        verbose: Whether to print the command being run and successful output
    """
    try:
        if verbose and not silent:
            print_info(f"Running command: {command}")
        
        result = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=capture_output,
            check=check
        )
        if verbose and not silent and result.stdout:
             print_success(f"Command output:\n{result.stdout}")
        return True, result
    except subprocess.CalledProcessError as e:
        if not silent:
            print_error(f"Command failed: {e}")
            if e.stderr:
                print_error(f"Error output: {e.stderr}")
        return False, e
    except Exception as e:
        if not silent:
            print_error(f"Error executing command: {str(e)}")
        return False, e


def prompt_enter_to_continue() -> None:
    """Display a prompt for user to press Enter to continue."""
    input(f"{Colors.BLUE}Press Enter to continue...{Colors.ENDC}")


def with_spinner(text: str, success_message: str = None, fail_message: str = None):
    """
    Context manager to run a block with a spinner.
    
    Usage:
        with with_spinner("Doing something...", "All done."):
            do_the_thing()
    """
    class SpinnerWrapper:
        def __enter__(self):
            self.spinner = yaspin(Spinners.dots, text=text)
            if sys.stdout.isatty():
                self.spinner.start()
            else:
                print_info(text)
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if sys.stdout.isatty():
                if exc_type is None:
                    self.spinner.ok("✓")
                    if success_message:
                        print_success(success_message)
                else:
                    self.spinner.fail("✗")
                    if fail_message:
                        print_error(fail_message)
            else:
                if exc_type is None:
                    if success_message:
                        print_success(success_message)
                else:
                    if fail_message:
                        print_error(fail_message)
            return False  # Don't suppress exceptions

    return SpinnerWrapper()


def country_code_to_flag(country_code: str) -> str:
    """Convert a 2-letter country code to a flag emoji."""
    if not country_code or len(country_code) != 2:
        return ""
    
    return "".join(chr(ord(c.upper()) + 127397) for c in country_code)


@functools.lru_cache(maxsize=32)
def get_region_display_name(region_code: str) -> str:
    """Get a display name for a region in the format: "europe-west2 (London, UK)"""
    try:
        regions_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "regions.json")
        
        with open(regions_path, "r") as f:
            regions_data = json.load(f)
                
        if region_code in regions_data:
            location_name = regions_data[region_code]["name"]
            return f"{region_code} ({location_name})"
        
        return region_code
    except Exception:
        return region_code

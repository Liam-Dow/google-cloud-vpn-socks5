"""
WireGuard service for VPN Manager.
Provides functionality for interacting with the local WireGuard VPN client.
"""

import os
import subprocess
from typing import Optional, List

from vpn_manager.utils import (
    run_command,
    print_info,
    print_success,
    print_warning,
    print_error
)


class WireGuardService:
    """Handles all interactions with the local WireGuard VPN client."""

    def __init__(self, config_file: str, verbose: bool = False):
        """Initialize the WireGuard service."""
        self.config_file = config_file
        self.verbose = verbose

    def is_connected(self) -> bool:
        """Check if the WireGuard VPN client is connected."""
        try:
            success, result = run_command("wg show interfaces", check=False, capture_output=True, silent=True, verbose=self.verbose)
            if success and result and hasattr(result, 'stdout'):
                 interfaces = result.stdout.strip().split()
                 return len(interfaces) > 0
            return False
        except Exception:
            return False

    def connect(self, verbose: bool = False) -> bool:
        """Connect the local WireGuard VPN client."""
        effective_verbose = verbose if verbose is not None else self.verbose

        if self.is_connected():
            print_warning("VPN client is already connected.")
            return True

        try:
            success, cmd_result = run_command(
                f"sudo wg-quick up {self.config_file}",
                check=False,
                capture_output=True,
                silent=True,
                verbose=effective_verbose
            )

            if not success:
                 print_error(f"Failed to execute wg-quick up command: {cmd_result}")
                 return False

            if self.is_connected():
                 return True
            else:
                 print_error("Failed to verify VPN client connection after 'wg-quick up'. Check logs.")
                 return False

        except Exception as e:
            print_error(f"Error executing 'wg-quick up': {e}")
            return False

    def disconnect(self, verbose: bool = False) -> bool:
        """Disconnect the local WireGuard VPN client."""
        effective_verbose = verbose if verbose is not None else self.verbose

        if not self.is_connected():
            print_warning("VPN client is already disconnected.")
            return True

        try:
            success, cmd_result = run_command(
                f"sudo wg-quick down {self.config_file}",
                check=False,
                capture_output=True,
                silent=True,
                verbose=effective_verbose
            )

            if not success:
                 print_error(f"Failed to execute wg-quick down command: {cmd_result}")

            if not self.is_connected():
                 return True
            else:
                 print_error("Could not verify VPN client disconnection after 'wg-quick down'.")
                 return False

        except Exception as e:
            print_error(f"Error executing 'wg-quick down': {e}")
            return False

    def _update_config_line(self, prefix: str, new_line_content: str, in_section: str = None) -> bool:
        """
        Update a specific line in the WireGuard config file.
        
        Args:
            prefix: The line prefix to search for (e.g., "Endpoint", "PublicKey")
            new_line_content: The new content for the line
            in_section: Optional section name to limit the search (e.g., "[Peer]")
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not os.path.exists(self.config_file):
            print_error(f"WireGuard configuration file not found at: {self.config_file}")
            return False

        try:
            with open(self.config_file, 'r') as file:
                config_data = file.readlines()

            with open(self.config_file, 'w') as file:
                in_target_section = in_section is None
                for line in config_data:
                    if in_section and line.strip() == in_section:
                        in_target_section = True
                        file.write(line)
                    elif in_target_section and line.strip().startswith(prefix):
                        file.write(f"{prefix} = {new_line_content}\n")
                    else:
                        file.write(line)

            return True
        except Exception as e:
            print_error(f"Error updating WireGuard configuration: {str(e)}")
            return False

    def update_config(self, new_public_ip: str, port: int, verbose: bool = False) -> bool:
        """Update the WireGuard client configuration with the new server IP address."""
        return self._update_config_line("Endpoint", f"{new_public_ip}:{port}")

    def update_server_public_key(self, public_key: str, verbose: bool = False) -> bool:
        """Update the WireGuard client configuration with the server's new public key."""
        return self._update_config_line("PublicKey", public_key, in_section="[Peer]")

    def set_allowed_ips(self, mode: str, verbose: bool = False) -> bool:
        """
        Update the WireGuard client configuration with appropriate AllowedIPs.
        
        Args:
            mode: Either "vpn" for full tunnel (0.0.0.0/0) or "socks5" for SOCKS5 proxy (10.0.0.1/32)
            verbose: Enable verbose output
        """
        allowed_ips = "0.0.0.0/0" if mode == "vpn" else "10.0.0.1/32"
        return self._update_config_line("AllowedIPs", allowed_ips)
    
    def display_config(self, verbose: bool = False) -> None:
        """Display the contents of the WireGuard client configuration file."""
        print_info(f"Displaying WireGuard client configuration: {self.config_file}")
        if not os.path.exists(self.config_file):
            print_error(f"WireGuard configuration file not found at: {self.config_file}")
            return

        try:
            with open(self.config_file, 'r') as file:
                config_content = file.read()
                print("\nCurrent WireGuard Client Configuration:\n")
                print(config_content)
        except Exception as e:
            print_error(f"Error reading WireGuard configuration: {str(e)}")
    
    def get_config_ip(self) -> Optional[str]:
        """Get the IP address from the WireGuard configuration file."""
        if not os.path.exists(self.config_file):
            return None

        try:
            with open(self.config_file, 'r') as file:
                config_content = file.read()
                for line in config_content.split('\n'):
                    if line.strip().startswith('Endpoint'):
                        return line.split('=')[1].strip().split(':')[0].strip()
            return None
        except Exception as e:
            print_error(f"Error reading WireGuard configuration: {str(e)}")
            return None

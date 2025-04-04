"""Status checking and reporting for VPN Manager."""

import re
from typing import Dict, Any, List, Optional, Tuple

# Local Imports
from vpn_manager.config import VPNConfig, VPNState
from vpn_manager.utils import (
    run_command,
    get_public_ip_info,
    Colors,
    country_code_to_flag
)


class StatusManager:
    """Manages status checking and state synchronization."""

    def __init__(self, config: VPNConfig, gcp_service, wireguard_service):
        """Initialize the status manager."""
        self.config = config
        self.gcp_service = gcp_service
        self.wireguard_service = wireguard_service

    def check_vpn_state(self, state: VPNState, verbose: bool = False) -> Dict[str, Any]:
        """
        Performs comprehensive checks on VPN state and synchronizes if needed.
        
        Args:
            state: The current VPN state (will be modified if sync occurs).
            verbose: Enable verbose output.

        Returns:
            dict: State information dictionary with keys for various status aspects.
        """
        changes = []
        state_info = {
            "wireguard_status": False,
            "internet_connection": False,
            "public_ip": None,
            "public_ip_country": None,
            "config_matches": True
        }
        
        # Store original state values for comparison
        original_state_instance_name = state.instance_name
        original_state_zone = state.zone
        original_state_region = state.region
        original_state_status = state.status
        
        # Run all checks
        self._check_internet_connectivity(state_info, verbose)
        raw_status = self._check_gcp_instance_status(state, state_info, changes, 
                                                    original_state_instance_name, 
                                                    original_state_zone, 
                                                    original_state_region, 
                                                    original_state_status, 
                                                    verbose)
        self._check_wireguard_connection(state_info, verbose)
        self._check_public_ip(state_info, verbose)
        self._check_wireguard_config_endpoint(state, state_info, raw_status, verbose)

        # Report changes if any were found
        if not state_info["config_matches"]:
            print("\nWARNING: Local state file 'vpn_state.json' was updated based on checks.")
            if verbose:
                for change in changes:
                    if change['field'] == "GCP instance status":
                        print(f"INFO: - Change: {change['field']} (Old: '{change['old']}', New: '{change['new']}')")

        return state_info

    def _check_internet_connectivity(self, state_info: Dict[str, Any], verbose: bool) -> None:
        """Check if internet is accessible."""
        print("INFO: Checking internet connectivity...")
        try:
            success, _ = run_command(
                f"ping -c 1 {self.config.connectivity_check_ip}",
                silent=True,
                check=True,
                verbose=verbose
            )
            if success:
                state_info["internet_connection"] = True
                print("SUCCESS: Internet: Connected")
            else:
                state_info["internet_connection"] = False
                print("ERROR: Internet: Disconnected")
        except Exception:
            state_info["internet_connection"] = False
            print("ERROR: Internet: Disconnected")

    def _check_gcp_instance_status(self, state: VPNState, state_info: Dict[str, Any], 
                                  changes: List[Dict[str, str]], 
                                  original_instance_name: Optional[str], 
                                  original_zone: Optional[str], 
                                  original_region: Optional[str], 
                                  original_status: Optional[str], 
                                  verbose: bool) -> Optional[str]:
        """Check GCP instance status and sync with local state if needed."""
        print("\nINFO: Checking GCP instance status...")
        raw_status = None
        gcp_status_synced = False
        
        if state.instance_name and state.zone:
            raw_status, display_status = self.gcp_service.get_vpn_status(state.instance_name, state.zone)

            if raw_status is not None:
                # Successfully got status from API
                gcp_status_synced = True
                print(f"SUCCESS: GCP Instance: {state.instance_name} (Status: {display_status}, Zone: {state.zone})")

                # Check if local state status matches reality
                print("INFO: Checking local state consistency...")
                if original_status != raw_status:
                    changes.append({
                        "field": "GCP instance status",
                        "old": original_status or "N/A",
                        "new": raw_status
                    })
                    state.status = raw_status
                    state_info["config_matches"] = False
                    print(f"WARNING: Local state status mismatch detected (was '{original_status}', now '{raw_status}'). Updated.")
                else:
                    print("SUCCESS: Local state status matches GCP.")
            else:
                # API call failed
                print(f"WARNING: Could not retrieve status for instance '{state.instance_name}'. API returned: {display_status}.")
                
                # Clear state if instance is truly gone or inaccessible
                if display_status in ["Not found", "Permission Denied"]:
                    if original_instance_name or original_zone or original_region or original_status:
                        changes.append({
                            "field": "GCP instance",
                            "old": f"Instance '{original_instance_name}' existed in local state",
                            "new": f"Status from API: {display_status}"
                        })
                        state.instance_name = None
                        state.zone = None
                        state.region = None
                        state.status = None
                        
                        if state.server_public_key:
                            changes.append({
                                "field": "Server Public Key",
                                "old": "Key existed in local state",
                                "new": "Cleared due to missing/inaccessible instance"
                            })
                            state.server_public_key = None
                            
                        state_info["config_matches"] = False
                        print(f"WARNING: Cleared stale instance details from local state due to API status: {display_status}.")
                        gcp_status_synced = True
                else:
                    print("ERROR: Failed to confirm instance status due to an API error. Local state remains unchanged.")
                    gcp_status_synced = False
        else:
            print("INFO: No instance details found in local state to check.")
            gcp_status_synced = True

        if not gcp_status_synced:
            print("ERROR: Failed to synchronize GCP status with local state.")
            
        return raw_status

    def _check_wireguard_connection(self, state_info: Dict[str, Any], verbose: bool) -> None:
        """Check if WireGuard is connected."""
        print("\nINFO: Checking WireGuard connection...")
        state_info["wireguard_status"] = self.wireguard_service.is_connected()
        if state_info["wireguard_status"]:
            print("SUCCESS: WireGuard: Connected")
        else:
            print("WARNING: WireGuard: Not connected")

    def _check_public_ip(self, state_info: Dict[str, Any], verbose: bool) -> None:
        """Check current public IP and location."""
        print("\nINFO: Checking public IP...")
        public_ip_info = get_public_ip_info(self.config.ip_info_service)
        if public_ip_info:
            ip = public_ip_info.get("ip")
            country = public_ip_info.get("country")
            state_info["public_ip"] = ip
            state_info["public_ip_country"] = country
            flag = country_code_to_flag(country) if country else ""
            print(f"SUCCESS: Public IP: {ip or 'N/A'} ({country or 'N/A'} {flag})")
        else:
            print("ERROR: Could not determine public IP")

    def _check_wireguard_config_endpoint(self, state: VPNState, state_info: Dict[str, Any], 
                                        raw_status: Optional[str], verbose: bool) -> None:
        """Check WireGuard config IP and compare with GCP IP if possible."""
        print("\nINFO: Checking WireGuard config endpoint...")
        config_ip = self.wireguard_service.get_config_ip()
        gcp_ip = None

        # Fetch GCP IP only if instance is supposed to be running
        if raw_status == "RUNNING" and state.instance_name and state.zone:
            gcp_ip = self.gcp_service.get_instance_public_ip(state.instance_name, state.zone)

        if config_ip:
            if gcp_ip:
                if config_ip == gcp_ip:
                    print(f"SUCCESS: WireGuard Config IP matches GCP IP: {config_ip}")
                else:
                    # Mismatch found
                    print(f"WARNING: WireGuard Config IP: {config_ip}")
                    print(f"WARNING: WireGuard config IP ({config_ip}) does not match current GCP instance IP ({gcp_ip}).")
                    print("INFO: Attempting to update local WireGuard configuration...")
                    update_success = self.wireguard_service.update_config(gcp_ip, self.config.wireguard_port, verbose=verbose)
                    if update_success:
                        print("SUCCESS: Local WireGuard configuration updated successfully.")
                    else:
                        print("ERROR: Failed to update local WireGuard configuration.")
                        state_info["config_matches"] = False
            else:
                print(f"SUCCESS: WireGuard Config IP: {config_ip}")
                if raw_status == "RUNNING":
                    print(f"WARNING: Could not verify config IP against GCP IP (failed to fetch GCP IP for '{state.instance_name}').")
        else:
            print("WARNING: Could not read Endpoint IP from WireGuard config (or file missing).")
            if gcp_ip:
                print("INFO: Instance is running but config IP is missing. Attempting to update...")
                update_success = self.wireguard_service.update_config(gcp_ip, self.config.wireguard_port, verbose=verbose)
                if update_success:
                    print("SUCCESS: Local WireGuard configuration updated successfully.")
                else:
                    print("ERROR: Failed to update local WireGuard configuration.")

    def get_state_summary(self, state: VPNState) -> Tuple[str, str]:
        """
        Generates a header and info line for the banner display.
        
        Returns:
            tuple: (header, info_line) for the banner format
        """
        # Determine VPN status
        vpn_status_display = "N/A"
        if state.instance_name and state.zone:
            vpn_status_display = state.status if state.status else "Fetching..."
            if state.status is None:
                _, vpn_status_display = self.gcp_service.get_vpn_status(state.instance_name, state.zone)
        
        # Check if WireGuard is connected and translate status for UI
        vpn_connected = self.wireguard_service.is_connected()
        display_status_ui = "STOPPED" if vpn_status_display == "TERMINATED" else vpn_status_display
        
        # Create header line based on connection status
        if vpn_connected:
            header = "[ VPN Manager - Connected ]"
        elif display_status_ui == "RUNNING":
            header = "[ VPN Manager - Ready ]"
        elif display_status_ui == "STOPPED":
            header = "[ VPN Manager - Stopped ]"
        else:
            header = "[ VPN Manager - Disconnected ]"
        
        # Get public IP info
        public_ip_info = get_public_ip_info(self.config.ip_info_service)
        ip_display = "Unknown"
        country_flag = ""
        if public_ip_info and public_ip_info.get("ip") and public_ip_info.get("country"):
            ip_display = public_ip_info.get("ip")
            country_code = public_ip_info.get("country")
            country_flag = f" ({country_code} {country_code_to_flag(country_code)})"
        
        # Get tunnel mode
        tunnel_mode = "VPN" if not state.tunnel_mode or state.tunnel_mode == "vpn" else "SOCKS5"
        
        # Create info line with key details
        instance_info = ""
        if state.instance_name and state.zone:
            instance_info = f"Instance: {state.instance_name} ({state.zone})"
        else:
            instance_info = "No VPN instance deployed" if display_status_ui == "N/A" else "Instance: N/A"
            
        info_line = f"Public IP: {ip_display}{country_flag}  •  Tunnel: {tunnel_mode}  •  {instance_info}"
        
        return header, info_line

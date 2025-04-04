#!/usr/bin/env python3
"""VPNManager Application Class - Orchestrates VPN lifecycle and user interaction."""

import sys
import traceback
import re

# Project imports - adapt paths if structure changes
from vpn_manager.config import ConfigManager, VPNConfig, VPNState
from vpn_manager.gcp import GCPService
from vpn_manager.wireguard import WireGuardService
from vpn_manager.status import StatusManager
from vpn_manager.ui import UIManager
from vpn_manager.utils import (
    print_info,
    print_success,
    print_warning,
    print_error,
    prompt_enter_to_continue,
    with_spinner
)


class VPNManager:
    """
    VPNManager is the central orchestrator that coordinates actions among
    GCPService, WireGuardService, ConfigManager, UIManager, and StatusManager.
    """

    def __init__(
        self,
        config_path: str,
        state_path: str,
        config: VPNConfig,
        config_manager: ConfigManager,
        gcp_service: GCPService,
        wireguard_service: WireGuardService,
        ui_manager: UIManager,
        status_manager: StatusManager,
        verbose: bool = False
    ):
        """Initialize the VPNManager with all needed services."""
        self.config_path = config_path
        self.state_path = state_path
        self.config_manager = config_manager
        self.gcp_service = gcp_service
        self.wireguard_service = wireguard_service
        self.ui_manager = ui_manager
        self.status_manager = status_manager
        self.verbose = verbose

        # Hold the loaded config and state
        self.config: VPNConfig = config
        # Load initial state (will be reloaded in run loop)
        self.state: VPNState = self.config_manager.load_state()

    def run(self) -> int:
        """
        Main interactive loop for TUI usage.
        
        Returns:
            int: Exit code (0 for success, 1 for error).
        """
        exit_code = 0
        while True:
            try:
                # Reload state each loop to ensure freshness
                self.state = self.config_manager.load_state()

                # Check WireGuard local connection status
                wg_connected = self.wireguard_service.is_connected()

                # Gather summary info using StatusManager (now returns header and info line)
                header_and_info = self.status_manager.get_state_summary(self.state)

                # Display summarised state to user with new format
                self.ui_manager.display_state_summary(header_and_info)

                # Prompt main menu for next action
                choice = self.ui_manager.prompt_main_menu(self.state, wg_connected)

                action_successful = True # Assume success unless handler returns False

                # --- Map choices to handler methods ---
                if choice == "Deploy":
                    region, zone = self.ui_manager.select_region_and_zone()
                    if region and zone:
                        deploy_success = self._handle_deploy_vpn(zone=zone, non_interactive=False)
                        action_successful = deploy_success
                        if deploy_success:
                            # After successful deployment, ask if user wants to connect
                            connect_now = self.ui_manager.confirm_action(
                                "Deployment successful. Would you like to connect to the VPN now?"
                            )
                            if connect_now:
                                action_successful = self._handle_connect(non_interactive=False)
                    else:
                        print_warning("Region/Zone selection cancelled or failed.")
                        action_successful = False

                elif choice == "Start VPN Server":
                    action_successful = self._handle_start_vpn(non_interactive=False)

                elif choice == "Stop VPN Server":
                     action_successful = self._handle_turn_off_vpn(non_interactive=False)

                elif choice == "Disconnect & Stop VPN Server":
                     if self._handle_disconnect(non_interactive=False):
                         action_successful = self._handle_turn_off_vpn(non_interactive=False)
                     else:
                         action_successful = False # Disconnect failed

                elif choice == "Delete VPN Server":
                    action_successful = self._handle_delete_vpn(non_interactive=False, force=False)

                elif choice == "Connect":
                    action_successful = self._handle_connect(non_interactive=False)

                elif choice == "Disconnect":
                    action_successful = self._handle_disconnect(non_interactive=False)
                    
                elif choice == "Change Tunnel Mode":
                    action_successful = self._handle_change_tunnel_mode(non_interactive=False)
                    
                elif choice == "Rotate IP Address":
                    action_successful = self._handle_ip_rotation(non_interactive=False)

                elif choice == "Run Status Check":
                    self._handle_check_vpn_state(non_interactive=False)
                    # Status check doesn't really "succeed" or "fail" in the same way

                elif choice == "View WireGuard Config":
                    self._handle_check_wireguard_config(non_interactive=False)
                    # Viewing config also neutral outcome

                elif choice == "Exit":
                    print_info("Exiting VPN Manager. Goodbye!")
                    break # Exit loop

                else:
                    print_warning(f"Unrecognised option: '{choice}'")
                    action_successful = False

                # Add pause only if an action was attempted (and interactive mode)
                if choice != "Exit":
                     if not action_successful:
                         print_warning("Previous action encountered an issue.")
                     prompt_enter_to_continue()

            except KeyboardInterrupt:
                print_info("\nReceived Ctrl+C. Exiting gracefully...")
                exit_code = 1 # Indicate interruption
                break
            except Exception as ex:
                print_error(f"An unexpected error occurred in the main loop: {ex}")
                if self.verbose:
                    traceback.print_exc()
                exit_code = 1 # Indicate error
                break
        return exit_code

    def _run_operation(self, operation_name, operation_func, *args, **kwargs):
        """
        Run an operation with spinner and error handling.
        
        Args:
            operation_name: Name of the operation for spinner text
            operation_func: Function to execute
            *args, **kwargs: Arguments to pass to operation_func
            
        Returns:
            tuple: (success, result) - success is bool, result is operation result or exception
        """
        try:
            with with_spinner(f"{operation_name}...", None):
                result = operation_func(*args, **kwargs)
                return True, result
        except Exception as e:
            print_error(f"{operation_name} failed: {e}")
            return False, e

    def _save_state(self):
        """Save the current state to disk."""
        try:
            with with_spinner("Saving state...", None):
                if not self.config_manager.save_state(self.state):
                    raise Exception("Failed to save state")
                return True
        except Exception as e:
            print_warning(f"State save issue: {e}")
            return False

    def _update_wireguard_config(self, public_ip, server_key=None):
        """
        Update WireGuard configuration with new IP and optionally server key.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with with_spinner("Updating WireGuard config...", None):
                ip_update_ok = self.wireguard_service.update_config(
                    public_ip, self.config.wireguard_port, verbose=self.verbose
                )
                if not ip_update_ok:
                    raise Exception("Failed to update IP in WireGuard config")
                
                # Update server key if provided
                if server_key:
                    key_update_ok = self.wireguard_service.update_server_public_key(
                        server_key, verbose=self.verbose
                    )
                    if not key_update_ok:
                        raise Exception("Failed to update server key in WireGuard config")
                
                return True
        except Exception as e:
            print_error(f"Config update failed: {e}")
            return False

    def _fetch_server_key(self, instance_name, zone):
        """
        Fetch server public key and update state and WireGuard config.
        
        Returns:
            tuple: (success, key) - success is bool, key is the server key or None
        """
        try:
            with with_spinner("Getting server public key...", None):
                server_key = self.gcp_service.get_server_public_key(instance_name, zone)
                if not server_key:
                    raise Exception("Could not retrieve server public key")
                
                self.state.server_public_key = server_key
                key_update_ok = self.wireguard_service.update_server_public_key(
                    server_key, verbose=self.verbose
                )
                if not key_update_ok:
                    raise Exception("Failed to update server key in WireGuard config")
                
                return True, server_key
        except Exception as e:
            print_warning(f"Public key retrieval issue: {e}")
            return False, None

    def _check_instance_exists(self):
        """Check if instance exists in state."""
        if not self.state.instance_name or not self.state.zone:
            print_error("No instance found in state. Cannot proceed. Please deploy first.")
            return False
        return True

    def _handle_deploy_vpn(self, zone: str, non_interactive: bool = False) -> bool:
        """Deploy a new GCP VPN instance in the specified zone."""
        # Extract region from zone (e.g., "us-central1-a" -> "us-central1")
        match = re.match(r"([a-z]+-[a-z0-9]+)", zone)
        if not match:
             print_error(f"Could not determine region from zone '{zone}'.")
             return False
        region = match.group(1)

        # Check if instance already exists in state - prompt for deletion
        if self.state.instance_name and self.state.zone:
            if not non_interactive:
                confirm = self.ui_manager.confirm_action(
                    f"An instance '{self.state.instance_name}' already exists. Delete it before deploying a new one?"
                )
                if confirm:
                    success, _ = self._run_operation(
                        "Deleting existing instance",
                        self._handle_delete_vpn,
                        non_interactive=True, 
                        force=True
                    )
                    if not success:
                        return False
                else:
                    print_warning("Deployment cancelled.")
                    return False
            else:
                 print_error(f"Cannot deploy: Instance '{self.state.instance_name}' already exists in state.")
                 return False

        # --- GCP Deployment ---
        success, result = self._run_operation(
            "Deploying VPN instance",
            self.gcp_service.deploy_vpn,
            region, zone
        )
        if not success:
            return False
            
        instance_name, deployed_region, deployed_zone, public_ip = result
        if not instance_name or not public_ip:
            print_error("Deployment unsuccessful. Instance name or public IP not returned.")
            return False

        # --- Fetch Server Public Key ---
        key_success, server_key = self._fetch_server_key(instance_name, deployed_zone)
        # Continue even if key fetch fails (non-fatal)

        # --- Update State ---
        self.state.instance_name = instance_name
        self.state.region = deployed_region
        self.state.zone = deployed_zone
        self.state.status = "RUNNING"
        self.state.server_public_key = server_key
        
        if not self._save_state():
            print_warning("State update issue. Continuing anyway.")

        # --- Update Local WireGuard Config ---
        if not self._update_wireguard_config(public_ip, server_key):
            return False
            
        return True

    def _handle_start_vpn(self, non_interactive: bool = False) -> bool:
        """Start the existing GCP VPN instance if present in state."""
        if not self._check_instance_exists():
            return False

        # Check current status first
        success, result = self._run_operation(
            "Checking instance status",
            self.gcp_service.get_vpn_status,
            self.state.instance_name, 
            self.state.zone
        )
        if not success:
            return False
            
        current_raw_status, current_display_status = result

        if current_raw_status == "RUNNING":
            print_warning(f"Instance '{self.state.instance_name}' is already running.")
            
            # Verify wg config and update if needed
            success, public_ip = self._run_operation(
                "Verifying configuration",
                self.gcp_service.get_instance_public_ip,
                self.state.instance_name, 
                self.state.zone
            )
            if not success or not public_ip:
                print_error("Could not get public IP for running instance")
                return False
                
            if not self._update_wireguard_config(public_ip):
                return False
                
            # Check/Update Key if needed
            if not self.state.server_public_key:
                key_success, server_key = self._fetch_server_key(
                    self.state.instance_name, 
                    self.state.zone
                )
                if key_success:
                    self._save_state()
            else:
                # Key exists in state, ensure WG config has it
                success, _ = self._run_operation(
                    "Updating server key in config",
                    self.wireguard_service.update_server_public_key,
                    self.state.server_public_key, 
                    verbose=self.verbose
                )
                if not success:
                    return False
                    
            return True

        elif current_raw_status is None: # Error or Not Found
            print_error(f"Could not confirm status of '{self.state.instance_name}' (status: {current_display_status}).")
            return False
        elif current_raw_status != "TERMINATED": # Not stopped, not running (e.g., STOPPING)
            print_error(f"Instance is in state '{current_display_status}'. Cannot start now.")
            return False
            
        # --- Instance is TERMINATED, proceed to start ---
        success, result = self._run_operation(
            "Starting VPN instance",
            self.gcp_service.turn_on_vpn,
            self.state, None, None
        )
        if not success:
            return False
            
        name, region, zone, public_ip = result
        if not name or not public_ip:
            print_error("Start command failed or did not return required info")
            return False
            
        # --- Update State ---
        self.state.status = "RUNNING"
        self.state.instance_name = name
        self.state.region = region
        self.state.zone = zone

        # --- Update Local WireGuard Config ---
        if not self._update_wireguard_config(public_ip):
            return False

        # --- Fetch Server Public Key if needed ---
        if not self.state.server_public_key:
            key_success, server_key = self._fetch_server_key(name, zone)
            # Continue even if key fetch fails (non-fatal)
        else:
            # Key exists in state, ensure WG config has it
            success, _ = self._run_operation(
                "Updating server key in config",
                self.wireguard_service.update_server_public_key,
                self.state.server_public_key, 
                verbose=self.verbose
            )
            # Continue even if key update fails (non-fatal)

        # --- Save State ---
        self._save_state()
        return True

    def _handle_turn_off_vpn(self, non_interactive: bool = False) -> bool:
        """Stop the current GCP VPN instance."""
        if not self._check_instance_exists():
            print_warning("No instance found in state to stop.")
            return True # Nothing to do, success.

        # --- Disconnect Local WireGuard First (if connected) ---
        if self.wireguard_service.is_connected():
            success, _ = self._run_operation(
                "Disconnecting",
                self._handle_disconnect,
                non_interactive=True
            )
            if not success:
                print_warning("Aborting instance stop.")
                return False

        # --- Stop GCP Instance ---
        success, stop_ok = self._run_operation(
            "Stopping VPN instance",
            self.gcp_service.turn_off_vpn,
            self.state.instance_name, 
            self.state.zone
        )
        if not success or not stop_ok:
            return False
            
        # --- Update State ---
        self.state.status = "TERMINATED" # GCE uses TERMINATED for stopped
        self._save_state()
        return True

    def _handle_delete_vpn(self, non_interactive: bool = False, force: bool = False) -> bool:
        """Permanently delete the GCP VPN instance."""
        if not self._check_instance_exists():
            print_warning("No instance found in state to delete.")
            return True # Nothing to do, success.

        # --- Confirm Action ---
        if not force:
            # Confirmation is only needed in interactive mode
            if not non_interactive:
                 confirmed = self.ui_manager.confirm_action(
                     f"Permanently delete instance '{self.state.instance_name}'? This cannot be undone."
                 )
                 if not confirmed:
                     print_info("Deletion cancelled.")
                     return False
            else:
                 # Non-interactive and not forced? Error out.
                 print_error("Deletion requires confirmation. Use --force flag when running non-interactively.")
                 return False

        # --- Disconnect Local WireGuard First (if connected) ---
        if self.wireguard_service.is_connected():
            success, _ = self._run_operation(
                "Disconnecting",
                self._handle_disconnect,
                non_interactive=True
            )
            if not success:
                print_warning("Aborting instance deletion.")
                return False

        # --- Delete GCP Instance ---
        instance_name_to_delete = self.state.instance_name  # Keep for message
        success, delete_ok = self._run_operation(
            "Deleting VPN instance",
            self.gcp_service.delete_vpn_server,
            self.state.instance_name, 
            self.state.zone
        )
        if not success or not delete_ok:
            return False
            
        # --- Clear State ---
        self.state.instance_name = None
        self.state.region = None
        self.state.zone = None
        self.state.status = None
        self.state.server_public_key = None
        
        self._save_state()
        return True

    def _handle_connect_with_mode_selection(self, non_interactive: bool = False, mode: str = None) -> bool:
        """Connect to VPN with mode selection if not specified."""
        # First check if already connected
        if self.wireguard_service.is_connected():
            print_warning("WireGuard is already connected.")
            return True
            
        # Determine which mode to use
        connection_mode = mode
        if not connection_mode and not non_interactive:
            # If no mode specified and interactive, prompt user
            connection_mode = self.ui_manager.prompt_connection_mode()
        elif not connection_mode:
            # Default to vpn mode in non-interactive mode if not specified
            connection_mode = "vpn"
        
        # Set AllowedIPs based on mode
        mode_display = "VPN" if connection_mode == "vpn" else "SOCKS5"
        success, _ = self._run_operation(
            f"Applying {mode_display} tunnel mode",
            self.wireguard_service.set_allowed_ips,
            connection_mode, 
            verbose=self.verbose
        )
        if not success:
            return False
            
        # Update state with tunnel mode
        self.state.tunnel_mode = connection_mode
        self._save_state()
        
        # Continue with the rest of the connection logic
        if not self._check_instance_exists():
            return False

        # --- Check Instance Status ---
        success, result = self._run_operation(
            "Checking instance status",
            self.gcp_service.get_vpn_status,
            self.state.instance_name, 
            self.state.zone
        )
        if not success:
            return False
            
        vpn_raw_status, vpn_display_status = result
        if vpn_raw_status != "RUNNING":
            print_error(f"Instance is not running (status: {vpn_display_status})")
            print_info("Please start the instance first.")
            return False

        # Check if server public key is available and update if needed
        if not self.state.server_public_key:
            key_success, _ = self._fetch_server_key(
                self.state.instance_name, 
                self.state.zone
            )
            if not key_success:
                print_warning("Cannot connect without server public key.")
                return False
                
            # Save state immediately after getting key
            self._save_state()
        else:
            # Key exists in state, ensure it's in the config file
            success, _ = self._run_operation(
                "Verifying server key in config",
                self.wireguard_service.update_server_public_key,
                self.state.server_public_key, 
                verbose=self.verbose
            )
            if not success:
                return False

        # --- Connect WireGuard ---
        success, _ = self._run_operation(
            "Connecting",
            self.wireguard_service.connect,
            verbose=self.verbose
        )
        if not success:
            print_warning("Check 'wg-quick' logs or permissions.")
            return False

        return True
        
    def _handle_connect(self, non_interactive: bool = False) -> bool:
        """Connect local WireGuard to the remote VPN server."""
        return self._handle_connect_with_mode_selection(non_interactive=non_interactive)

    def _handle_disconnect(self, non_interactive: bool = False) -> bool:
        """Disconnect local WireGuard if connected."""
        if not self.wireguard_service.is_connected():
            print_warning("WireGuard is already disconnected.")
            return True # Already in desired state

        success, _ = self._run_operation(
            "Disconnecting",
            self.wireguard_service.disconnect,
            verbose=self.verbose
        )
        if not success:
            print_warning("Interface may be stuck. Try again or check permissions.")
            return False

        return True

    def _handle_check_vpn_state(self, non_interactive: bool = False) -> None:
        """Perform a thorough status check using StatusManager."""
        # Reload the current state before checking
        self.state = self.config_manager.load_state()

        # StatusManager.check_vpn_state performs checks, prints output,
        # and modifies the state object directly if needed
        _ = self.status_manager.check_vpn_state(self.state, verbose=self.verbose)

        # Save the state back to the file, as check_vpn_state might have modified it
        if not self._save_state():
            print_error("Failed to save state after status check. File may be out of sync.")
        elif self.verbose:
             print_info("State saved after status check.")

    def _handle_ip_rotation(self, non_interactive: bool = False, target_zone: str = None) -> bool:
        """Implement IP rotation workflow with confirmation and region/zone selection."""
        # 1. Check if we have a running instance
        if not self._check_instance_exists():
            return False
        
        # Store old instance details
        old_instance = self.state.instance_name
        old_zone = self.state.zone
        old_region = self.state.region
        
        # 2. Region/Zone selection
        deploy_region = old_region
        deploy_zone = old_zone
        
        if non_interactive:
            # In non-interactive mode, use provided zone or fall back to current
            if target_zone:
                # Extract region from zone (e.g., "us-central1-a" -> "us-central1")
                match = re.match(r"([a-z]+-[a-z0-9]+)", target_zone)
                if not match:
                    print_error(f"Could not determine region from zone '{target_zone}'.")
                    return False
                deploy_region = match.group(1)
                deploy_zone = target_zone
        else:
            # In interactive mode, ask if user wants to change region/zone
            use_same_location = self.ui_manager.confirm_action(
                f"Use the same region ({old_region}) and zone ({old_zone}) for the new server?"
            )
            
            if not use_same_location:
                # Let user select a new region and zone
                new_region, new_zone = self.ui_manager.select_region_and_zone()
                if new_region and new_zone:
                    deploy_region = new_region
                    deploy_zone = new_zone
                else:
                    print_warning("Region/Zone selection cancelled or failed. Using current location.")
        
        # 3. Get next rotation number and create suffix
        next_rotation = self.gcp_service.get_next_rotation_number(deploy_region, deploy_zone)
        rotation_suffix = f"rotate{next_rotation}"
        
        # 4. Deploy new instance with rotation suffix
        try:
            success, result = self._run_operation(
                f"Deploying a new VPN instance in zone '{deploy_zone}' for IP rotation",
                self.gcp_service.deploy_vpn,
                deploy_region, 
                deploy_zone, 
                rotation_suffix=rotation_suffix
            )
            if not success:
                return False
                
            instance_name, deployed_region, deployed_zone, public_ip = result
        except Exception as e:
            print_error(f"Deployment API call failed: {e}")
            return False
        
        if not instance_name or not public_ip:
            print_error("Deployment unsuccessful. Instance name or public IP not returned. Check GCP logs.")
            return False
        
        # Get new server's public key
        success, server_key = self._run_operation(
            "Getting server public key",
            self.gcp_service.get_server_public_key,
            instance_name, deployed_zone
        )
        if not success or not server_key:
            print_warning("Could not retrieve server public key from new instance.")
        
        # Get location info for new IP
        from vpn_manager.utils import get_public_ip_info, country_code_to_flag
        location_info = ""
        ip_info = get_public_ip_info(self.config.ip_info_service)
        if ip_info and ip_info.get("country"):
            country = ip_info.get("country")
            flag = country_code_to_flag(country)
            location_info = f" ({country} {flag})"
        
        # 3. Show new IP and get confirmation
        print_success(f"✓ Deployment successful: {public_ip}{location_info}")
        
        if not non_interactive:
            confirmed = self.ui_manager.confirm_action(
                "Switch to the new IP now? (This will disconnect and reconnect your VPN)"
            )
            if not confirmed:
                print_info("IP rotation cancelled.")
                # Ask if user wants to keep or delete the new server
                keep_new = self.ui_manager.confirm_action(
                    f"Keep the new server instance '{instance_name}' running? (No will delete it)"
                )
                if not keep_new:
                    print_info(f"Deleting new instance '{instance_name}'...")
                    self.gcp_service.delete_vpn_server(instance_name, deployed_zone)
                return False
        
        # 4. If confirmed, update config and switch
        
        # First disconnect if connected
        if self.wireguard_service.is_connected():
            success, _ = self._run_operation(
                "Switching to new VPN server",
                self._handle_disconnect,
                non_interactive=True
            )
            if not success:
                print_error("Failed to disconnect from current VPN server. Aborting switch.")
                return False
        
        # Update local WireGuard config
        if not self._update_wireguard_config(public_ip, server_key):
            print_error("Failed to update local WireGuard configuration. Aborting switch.")
            return False
        
        # Update state with new server details
        self.state.instance_name = instance_name
        self.state.region = deployed_region
        self.state.zone = deployed_zone
        self.state.status = "RUNNING"
        self.state.server_public_key = server_key
        
        if not self._save_state():
            print_error("Failed to save updated state. Continuing anyway...")
        
        # Reconnect with the same mode as before
        tunnel_mode = self.state.tunnel_mode or "vpn"  # Default to vpn mode if not set
        if not self._handle_connect_with_mode_selection(non_interactive=True, mode=tunnel_mode):
            print_error("Failed to connect to new VPN server.")
            return False
        
        # Delete old server
        success, _ = self._run_operation(
            f"Deleting old VPN instance '{old_instance}'",
            self.gcp_service.delete_vpn_server,
            old_instance, old_zone
        )
        if not success:
            print_warning(f"Failed to delete old instance '{old_instance}'. You may want to clean it up manually.")
        
        print_success(f"✓ Rotated to new IP {public_ip}{location_info}")
        return True
        
    def _handle_change_tunnel_mode(self, non_interactive: bool = False) -> bool:
        """Change the VPN tunnel mode (VPN or SOCKS5)."""
        # Get current tunnel mode from state or default to "vpn"
        current_mode = self.state.tunnel_mode or "vpn"
        mode_display = "VPN" if current_mode == "vpn" else "SOCKS5"
        
        # Display current mode
        print_info(f"Current tunnel mode: {mode_display}")
        
        # In non-interactive mode, toggle mode
        if non_interactive:
            new_mode = "socks5" if current_mode == "vpn" else "vpn"
        else:
            # Let user choose mode
            new_mode = self.ui_manager.prompt_connection_mode()
        
        # If mode hasn't changed, nothing to do
        if new_mode == current_mode:
            print_info(f"Tunnel mode unchanged ({mode_display}).")
            return True
        
        # Update WireGuard config
        new_mode_display = "VPN" if new_mode == "vpn" else "SOCKS5"
        success, _ = self._run_operation(
            f"Updating tunnel mode to {new_mode_display}",
            self.wireguard_service.set_allowed_ips,
            new_mode, 
            verbose=self.verbose
        )
        if not success:
            return False
            
        # Update state
        self.state.tunnel_mode = new_mode
        if not self._save_state():
            print_warning("Failed to save tunnel mode to state file")
        
        # If connected, ask if user wants to reconnect to apply changes
        if self.wireguard_service.is_connected():
            if not non_interactive:
                reconnect = self.ui_manager.confirm_action(
                    "Would you like to disconnect and reconnect now to apply changes?"
                )
                if reconnect:
                    success, _ = self._run_operation(
                        "Disconnecting",
                        self._handle_disconnect,
                        non_interactive=True
                    )
                    if not success:
                        print_warning("Please disconnect manually and reconnect.")
                        return False
                        
                    success, _ = self._run_operation(
                        "Connecting",
                        self._handle_connect_with_mode_selection,
                        non_interactive=True, 
                        mode=new_mode
                    )
                    if not success:
                        print_warning("Please reconnect manually.")
                        return False
        
        return True
    
    def _handle_check_wireguard_config(self, non_interactive: bool = False) -> None:
        """Display the local WireGuard config on screen."""
        # Pass verbose to display_config method
        self.wireguard_service.display_config(verbose=self.verbose)

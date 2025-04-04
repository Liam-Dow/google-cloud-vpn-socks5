"""User interface for VPN Manager."""

from InquirerPy import inquirer
from InquirerPy.separator import Separator
from typing import List, Optional, Dict, Any, Tuple

from vpn_manager.config import VPNState
from vpn_manager.utils import Colors, get_region_display_name


class UIManager:
    """Manages the user interface and interactions."""
    
    def __init__(self, gcp_service):
        """Initialize the UI manager with GCP service for region lookups."""
        self.gcp_service = gcp_service
    
    def _get_menu_actions(self, state: VPNState, vpn_connected: bool) -> Dict[str, List[str]]:
        """Get available actions based on current state."""
        actions = {
            "vpn_manager": [],
            "diagnostics": ["Run Status Check", "View WireGuard Config"]
        }
        
        # Determine VPN Manager actions based on state
        if state.status is None:
            actions["vpn_manager"].append("Deploy")
        elif state.status == "RUNNING":
            if vpn_connected:
                actions["vpn_manager"].extend(["Disconnect & Stop VPN Server", "Change Tunnel Mode", "Disconnect"])
            else:
                actions["vpn_manager"].extend(["Stop VPN Server", "Connect"])
            actions["vpn_manager"].extend(["Rotate IP Address", "Delete VPN Server"])
        else:  # TERMINATED or other states
            actions["vpn_manager"].extend(["Start VPN Server", "Delete VPN Server"])
            
        return actions
    
    def prompt_main_menu(self, state: VPNState, vpn_connected: bool) -> str:
        """Display the main menu with actions based on current state."""
        actions = self._get_menu_actions(state, vpn_connected)
        
        # Build menu
        choices = []
        choices.extend(actions["vpn_manager"])
        choices.append(Separator("---------------"))
        choices.extend(actions["diagnostics"])
        choices.append(Separator("---------------"))
        choices.append("Exit")

        return inquirer.select(
            message="Choose an action:",
            choices=choices
        ).execute()
    
    def select_region_and_zone(self) -> Tuple[Optional[str], Optional[str]]:
        """Prompt user to select a region and zone."""
        # 1) Prompt for region
        regions = self.gcp_service.get_regions()
        if not regions: 
            return None, None 
        
        # Format region display names
        for region in regions:
            region_code = region["value"]
            location = get_region_display_name(region_code).replace(f"{region_code} (", "").replace(")", "")
            region["name"] = f"{region_code} | {location}"
        
        region_code = inquirer.select(
            message="Select a region:",
            choices=regions
        ).execute()
        
        # 2) Prompt for zone
        zones = self.gcp_service.get_zones(region_code)
        if not zones:
            print(f"No zones found (or zone fetching failed) for region {region_code}.")
            return region_code, None

        # Format zone display names
        for zone in zones:
            zone_code = zone["value"]
            zone_letter = zone_code.split('-')[-1]
            zone["name"] = f"{zone_code} | Zone {zone_letter.upper()}"

        zone_code = inquirer.select(
            message="Select a zone:",
            choices=zones
        ).execute()

        return region_code, zone_code
    
    def display_state_summary(self, header_and_info: Tuple[str, str]) -> None:
        """Display a summary of the current VPN state."""
        header, info_line = header_and_info
        print("\n=======================" + header + "=======================")
        print(info_line)
        print("----------------------------------------------------------------------------\n")
    
    def confirm_action(self, message: str) -> bool:
        """Ask user to confirm an action."""
        return inquirer.confirm(message=message).execute()
        
    def prompt_connection_mode(self) -> str:
        """Prompt user to select a VPN connection mode."""
        return inquirer.select(
            message="Select connection mode:",
            choices=[
                {"name": "VPN (route all traffic through VPN)", "value": "vpn"},
                {"name": "SOCKS5 (only route SOCKS5 proxy traffic through VPN)", "value": "socks5"},
            ]
        ).execute()

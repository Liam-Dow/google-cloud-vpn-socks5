"""Configuration management for VPN Manager."""

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Dict, Any


@dataclass
class WireguardClient:
    """Represents a WireGuard client configuration."""
    name: str
    public_key: str
    allowed_ip: str


@dataclass
class VPNConfig:
    """Application configuration settings loaded from config.json."""
    project_id: str
    network_tier: str 
    machine_tags: List[str]
    instance_prefix: str
    machine_type: str
    wireguard_port: int
    wireguard_clients: List[WireguardClient]
    wireguard_config_file: str
    ip_info_service: str
    connectivity_check_ip: str

    # Authentication Fields
    auth_method: Optional[str] = None  # e.g., "sa_key", "adc_impersonation", "adc_user"
    service_account_email: Optional[str] = None # Required for logging/verification if using ADC Imp.
    service_account_key_path: Optional[str] = None # Required if auth_method is "sa_key"


@dataclass
class VPNState:
    """VPN deployment state tracking."""
    instance_name: Optional[str] = None
    region: Optional[str] = None
    zone: Optional[str] = None
    status: Optional[str] = None
    server_public_key: Optional[str] = None
    tunnel_mode: Optional[str] = None  # "vpn" or "socks5"


class ConfigManager:
    """Manages application configuration and state."""

    # Default configuration values used when config file is missing or corrupted
    DEFAULT_CONFIG = {
        "project_id": "my-vpn-project",
        "network_tier": "PREMIUM",
        "machine_tags": ["wireguard"],
        "instance_prefix": "vpn-server",
        "machine_type": "e2-medium",
        "wireguard_port": 51820,
        "wireguard_clients": [],
        "wireguard_config_file": "/opt/homebrew/etc/wireguard/wg0.conf",
        "ip_info_service": "http://ipinfo.io/json",
        "connectivity_check_ip": "8.8.8.8"
    }

    def __init__(self, config_path: str, state_path: str):
        """Initialize the configuration manager."""
        self.config_path = config_path
        self.state_path = state_path
        self._ensure_config_dir()
    
    def _ensure_config_dir(self) -> None:
        """Ensure the configuration directory exists."""
        config_dir = os.path.dirname(self.config_path)
        os.makedirs(Path(config_dir), exist_ok=True)
    
    def load_config(self) -> VPNConfig:
        """Load application configuration settings from a JSON file."""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as file:
                    config_dict = json.load(file)
                
                # Fill in missing keys with defaults
                for key, default_value in self.DEFAULT_CONFIG.items():
                    if key not in config_dict:
                        print(f"Warning: Missing '{key}' in config file. Using default value.")
                        config_dict[key] = default_value
                
                return self._create_config_from_dict(config_dict)
            else:
                print(f"Warning: Config file {self.config_path} not found. Using default configuration.")
                return self._create_config_from_dict(dict(self.DEFAULT_CONFIG))
        except json.JSONDecodeError:
            print(f"Error: Config file {self.config_path} is corrupted. Using default configuration.")
            return self._create_config_from_dict(dict(self.DEFAULT_CONFIG))
        except Exception as e:
            print(f"Error loading configuration: {str(e)}. Using default configuration.")
            return self._create_config_from_dict(dict(self.DEFAULT_CONFIG))
    
    def _create_config_from_dict(self, config_dict: Dict[str, Any]) -> VPNConfig:
        """Create a VPNConfig object from a dictionary."""
        # Process wireguard_clients to convert them to proper objects
        if "wireguard_clients" in config_dict:
            clients = []
            for client_dict in config_dict["wireguard_clients"]:
                clients.append(WireguardClient(**client_dict))
            config_dict["wireguard_clients"] = clients
        
        # Remove legacy machine_image field if present
        if "machine_image" in config_dict:
            print("Note: Ignoring legacy 'machine_image' field in config - no longer required")
            config_dict.pop("machine_image")
        
        return VPNConfig(**config_dict)
    
    def load_state(self) -> VPNState:
        """Load VPN state from state tracking file."""
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, 'r') as file:
                    state_dict = json.load(file)
                
                # Filter out any None values represented as "null" in JSON
                filtered_state = {k: v for k, v in state_dict.items() if v != "null"}
                
                return VPNState(**filtered_state)
            else:
                return VPNState()  # Use defaults if state file doesn't exist
        except json.JSONDecodeError:
            print(f"Error: State file {self.state_path} is corrupted. Using default state.")
            return VPNState()
        except Exception as e:
            print(f"Error loading state: {str(e)}. Using default state.")
            return VPNState()
    
    def save_state(self, state: VPNState) -> bool:
        """Save VPN state to state tracking file."""
        try:
            self._ensure_config_dir()
            
            state_dict = asdict(state)
            
            with open(self.state_path, 'w') as file:
                json.dump(state_dict, file, indent=4)
            return True
        except Exception as e:
            print(f"Error saving state: {str(e)}")
            return False

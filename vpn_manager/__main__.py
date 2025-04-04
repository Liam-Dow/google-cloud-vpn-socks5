#!/usr/bin/env python3
"""
Entry point for the VPN Manager application.

This module provides the CLI entry point for the VPN Manager when
run as a Python package (`python -m vpn_manager`).
"""

import os
import sys
from pathlib import Path

from vpn_manager.app import VPNManager
from vpn_manager.utils import print_error

def main():
    """Main entry point for the VPN Manager application."""
    # Get the application directory
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Configuration file paths
    config_path = os.path.join(app_dir, "config.json")
    state_path = os.path.join(app_dir, "vpn_state.json")
    
    try:
        # Initialize and run the VPN Manager
        manager = VPNManager(config_path, state_path)
        return manager.run()
    except Exception as e:
        print_error(f"Application failed to start: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

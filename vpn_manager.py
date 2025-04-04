#!/usr/bin/env python3
"""VPN Manager - CLI tool for deploying and managing a WireGuard VPN on GCP."""

import os
import sys
import argparse

from vpn_manager.app import VPNManager
from vpn_manager.config import ConfigManager
from vpn_manager.utils import print_error, print_info, print_warning, print_success
from vpn_manager.gcp import GCPService
from vpn_manager.wireguard import WireGuardService
from vpn_manager.ui import UIManager
from vpn_manager.status import StatusManager

def apply_auth_environment(auth_method: str, key_path: str, service_account_email: str, verbose: bool) -> bool:
    """Sets environment variables for the chosen auth method. Returns success status."""
    if auth_method == "sa_key":
        if not key_path:
            print_error("Auth method 'sa_key' but no key path provided.")
            return False
        abs_key_path = os.path.abspath(key_path)
        if not os.path.exists(abs_key_path):
            print_error(f"Service Account key not found: {abs_key_path}")
            return False
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = abs_key_path
        if verbose:
            print_info(f"Using service account key at: {abs_key_path}")
    elif auth_method in ["adc", "impersonation"]:
        if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ and verbose:
            print_warning("GOOGLE_APPLICATION_CREDENTIALS is set, which overrides pure ADC.")
        if auth_method == "impersonation" and not service_account_email:
            print_error("Auth method 'impersonation' but no service account email provided.")
            return False
        if verbose:
            print_info(f"Auth method '{auth_method}'. No key file environment variable needed.")
    else:
        print_error(f"Unrecognised auth method: {auth_method}")
        return False
    return True

def _determine_auth_settings(args, config):
    """Determine authentication method, key path, and service account email based on args and config."""
    config_auth_method = getattr(config, "auth_method", None)
    config_sa_key = getattr(config, "service_account_key_path", None)
    config_sa_email = getattr(config, "service_account_email", None)
    
    if args.auth_method_arg:
        return args.auth_method_arg, None, None
    elif args.sa_impersonation_email_arg is not None:
        sa_email = config_sa_email if args.sa_impersonation_email_arg is True else args.sa_impersonation_email_arg
        return "impersonation", None, sa_email
    elif args.sa_key_path_arg:
        return "sa_key", args.sa_key_path_arg, None
    elif config_auth_method:
        return config_auth_method, config_sa_key, config_sa_email
    else:
        return "adc", None, None

def _initialize_gcp_service(config, auth_method, verbose):
    """Initialize GCP service with retry for ADC re-auth."""
    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        try:
            service = GCPService(config, auth_method=auth_method, verbose=verbose)
            if verbose:
                print_success("GCP service initialized successfully.")
            return service
        except ConnectionError as e:
            if auth_method == "adc" and attempt == 1:
                err_text = str(e).lower()
                if "could not find default credentials" in err_text or "credentials" in err_text:
                    print_error(f"GCP auth error: {e}")
                    print_info("Try running 'gcloud auth application-default login'.")
                    from InquirerPy import inquirer
                    confirm = inquirer.confirm(
                        message="Run 'gcloud auth application-default login' now?",
                        default=True
                    ).execute()
                    if confirm:
                        from vpn_manager.utils import run_command
                        success, _ = run_command("gcloud auth application-default login",
                                               silent=False, check=False, capture_output=False)
                        if success:
                            print_success("Re-auth successful. Retrying GCP initialization...")
                            continue
                        else:
                            print_error("gcloud login failed or cancelled.")
                            return None
                    else:
                        print_info("User declined re-auth. Exiting.")
                        return None
                else:
                    print_error(f"Connection error (ADC) on attempt {attempt}: {e}")
                    return None
            else:
                print_error(f"GCP initialization failed (attempt {attempt}): {e}")
                return None
        except Exception as e:
            print_error(f"Unexpected error in GCP init: {e}")
            return None
    
    print_error("Failed to establish GCP connection after retries.")
    return None

def main():
    parser = argparse.ArgumentParser(
        description="Manage a personal WireGuard VPN on GCP.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    # General flags
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output.")

    # Authentication Options
    auth_group = parser.add_argument_group("Authentication")
    auth_group.add_argument("--adc", action="store_const", dest="auth_method_arg", const="adc",
                          help="Use Application Default Credentials.")
    auth_group.add_argument("--impersonate", type=str, nargs="?", dest="sa_impersonation_email_arg",
                          const=True, metavar="SA_EMAIL",
                          help="Use ADC with service account impersonation.\nOptionally provide SA email.")
    auth_group.add_argument("--sa-key", type=str, dest="sa_key_path_arg", metavar="KEY_FILE_PATH",
                          help="Use a service account key file.")

    # VPN Actions (mutually exclusive)
    vpn_action_group = parser.add_argument_group("VPN Actions")
    exclusive = vpn_action_group.add_mutually_exclusive_group()
    exclusive.add_argument("--deploy", action="store_true", help="Deploy a new VPN server (requires --zone).")
    exclusive.add_argument("--start", action="store_true", help="Start existing VPN server.")
    exclusive.add_argument("--stop", action="store_true", help="Stop existing VPN server.")
    exclusive.add_argument("--delete", action="store_true", help="Delete VPN server.")
    exclusive.add_argument("--connect", nargs="?", const="vpn", choices=["vpn", "socks5"],
                         help="Connect local WireGuard (optional mode: vpn or socks5).")
    exclusive.add_argument("--disconnect", action="store_true", help="Disconnect local WireGuard.")
    exclusive.add_argument("--rotate-ip", action="store_true", help="Rotate VPN server public IP.")
    exclusive.add_argument("--status", action="store_true", help="Show VPN and connection status.")
    exclusive.add_argument("--show-config", action="store_true", help="Show local WireGuard configuration.")

    # Extra Options
    extra_group = parser.add_argument_group("Extra Options")
    extra_group.add_argument("--zone", type=str, metavar="ZONE", help="Specify GCP zone (e.g. europe-west1-b).")
    extra_group.add_argument("--force", action="store_true", help="Skip confirmation prompts.")

    args = parser.parse_args()

    # Determine config paths
    app_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(app_dir, "config.json")
    state_path = os.path.join(app_dir, "vpn_state.json")

    # Load config & state
    config_manager = ConfigManager(config_path, state_path)
    config = config_manager.load_config()
    state = config_manager.load_state()

    # Determine authentication settings
    chosen_auth_method, chosen_key_path, chosen_sa_email = _determine_auth_settings(args, config)
    
    if args.verbose:
        if args.auth_method_arg:
            print_info(f"Using auth method from --adc flag: '{chosen_auth_method}'")
        elif args.sa_impersonation_email_arg is not None:
            email_source = "config" if args.sa_impersonation_email_arg is True else "CLI"
            print_info(f"Using impersonation with SA from {email_source}: {chosen_sa_email}")
        elif args.sa_key_path_arg:
            print_info(f"Using service account key from --sa-key: {chosen_key_path}")
        elif getattr(config, "auth_method", None):
            print_info(f"Using auth method from config.json: '{chosen_auth_method}'")
        else:
            print_info("No auth specified in CLI or config. Defaulting to 'adc'.")

    # Apply environment for chosen method
    if not apply_auth_environment(chosen_auth_method, chosen_key_path, chosen_sa_email, args.verbose):
        return 1

    # Initialize GCP service
    gcp_service = _initialize_gcp_service(config, chosen_auth_method, args.verbose)
    if not gcp_service:
        return 1

    # Initialize other services
    wireguard_service = WireGuardService(config.wireguard_config_file, verbose=args.verbose)
    ui_manager = UIManager(gcp_service)
    status_manager = StatusManager(config, gcp_service, wireguard_service)

    manager = VPNManager(
        config_path, state_path,
        config=config, config_manager=config_manager,
        gcp_service=gcp_service, wireguard_service=wireguard_service,
        ui_manager=ui_manager, status_manager=status_manager,
        verbose=args.verbose
    )

    # Validate arguments
    if args.deploy and not args.zone:
        parser.error("--deploy requires --zone to be specified")
    
    # Dispatch CLI actions using a declarative approach
    action_handlers = {
        'deploy': lambda: manager._handle_deploy_vpn(args.zone, non_interactive=True),
        'start': lambda: manager._handle_start_vpn(non_interactive=True),
        'stop': lambda: manager._handle_turn_off_vpn(non_interactive=True),
        'delete': lambda: manager._handle_delete_vpn(non_interactive=True, force=args.force),
        'connect': lambda: manager._handle_connect_with_mode_selection(non_interactive=True, mode=args.connect),
        'disconnect': lambda: manager._handle_disconnect(non_interactive=True),
        'status': lambda: manager._handle_check_vpn_state(non_interactive=True) or True,  # Always returns True
        'show_config': lambda: manager._handle_check_wireguard_config(non_interactive=True) or True,  # Always returns True
        'rotate_ip': lambda: manager._handle_ip_rotation(non_interactive=True, target_zone=args.zone)
    }
    
    # Execute the appropriate action handler if an action was specified
    for action, handler in action_handlers.items():
        if getattr(args, action, False):
            print_info(f"Executing action: {action.replace('_', ' ')}...")
            if not handler():
                return 1
            return 0
    
    # If no action was taken, run the interactive TUI
    if not args.verbose:
        print_info("Starting VPN Manager...")
    return manager.run()

if __name__ == "__main__":
    sys.exit(main())

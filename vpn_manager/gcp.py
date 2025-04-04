"""
GCP service for VPN Manager using google-cloud-python library (compute_v1).
Provides functionality for deploying/stopping/deleting VPN instances.
"""

import os
import re
import time
from typing import Tuple, Optional, List, Dict, Any, Union

from google.cloud import compute_v1

# Local imports
from vpn_manager.config import VPNConfig, VPNState, WireguardClient
from vpn_manager.utils import (
    run_command,
    print_info,
    print_success,
    print_error,
    print_warning
)


class GCPService:
    """Handles interactions with GCP using compute_v1 + environment-based auth."""

    def __init__(self, config: VPNConfig, auth_method: str, verbose: bool = False):
        """Store references to config/auth but do not create any GCP clients yet."""
        self.config = config
        self.auth_method = auth_method
        self.verbose = verbose
        self.project_id = config.project_id
        self._regions_client = compute_v1.RegionsClient()
        self._instances_client = None
        self._zones_client = None
        self._zone_operations_client = None
        self._global_operations_client = None

        if self.verbose:
            print_info(f"GCPService constructed (project: {self.project_id}, auth: {self.auth_method}).")

    @property
    def instances_client(self) -> compute_v1.InstancesClient:
        """Lazily creates and returns a compute_v1.InstancesClient."""
        if self._instances_client is None:
            self._instances_client = compute_v1.InstancesClient()
        return self._instances_client

    @property
    def zones_client(self) -> compute_v1.ZonesClient:
        """Lazily creates and returns a compute_v1.ZonesClient."""
        if self._zones_client is None:
            self._zones_client = compute_v1.ZonesClient()
        return self._zones_client

    @property
    def regions_client(self) -> compute_v1.RegionsClient:
        """Lazily creates and returns a compute_v1.RegionsClient."""
        if self._regions_client is None:
            self._regions_client = compute_v1.RegionsClient()
        return self._regions_client

    @property
    def zone_operations_client(self) -> compute_v1.ZoneOperationsClient:
        """Lazily creates and returns a compute_v1.ZoneOperationsClient."""
        if self._zone_operations_client is None:
            self._zone_operations_client = compute_v1.ZoneOperationsClient()
        return self._zone_operations_client

    @property
    def global_operations_client(self) -> compute_v1.GlobalOperationsClient:
        """Lazily creates and returns a compute_v1.GlobalOperationsClient."""
        if self._global_operations_client is None:
            self._global_operations_client = compute_v1.GlobalOperationsClient()
        return self._global_operations_client

    def get_regions(self) -> List[Dict[str, str]]:
        """Returns a list of all region names available to the project."""
        results = []
        try:
            for region in self.regions_client.list(project=self.project_id):
                results.append({"name": region.name, "value": region.name})
            results.sort(key=lambda x: x["value"])
        except Exception as e:
            if self.verbose:
                print_error(f"Failed to list regions: {e}")
        return results

    def get_zones(self, region_code: str) -> List[Dict[str, str]]:
        """Returns a list of zones whose names start with `region_code`."""
        results = []
        try:
            filter_str = f'name:{region_code}-*'
            list_req = compute_v1.ListZonesRequest(project=self.project_id, filter=filter_str)

            for zone in self.zones_client.list(request=list_req):
                results.append({"name": zone.name, "value": zone.name})

            results.sort(key=lambda x: x["value"])
        except Exception as e:
            if self.verbose:
                print_error(f"Failed to list zones for region '{region_code}': {e}")
        return results

    def get_vpn_status(self, instance_name: str, zone: str) -> Tuple[Optional[str], str]:
        """
        Returns (raw_status, display_status).
        If instance is not found, returns (None, "Not found").
        If error, returns (None, "Error").
        """
        if not instance_name or not zone:
            return None, "Not deployed"
        try:
            req = compute_v1.GetInstanceRequest(project=self.project_id, zone=zone, instance=instance_name)
            instance = self.instances_client.get(request=req)
            raw_status = str(instance.status) if instance.status else "UNKNOWN"
            # GCE returns "TERMINATED" for a stopped instance
            display_status = "STOPPED" if raw_status == "TERMINATED" else raw_status
            return raw_status, display_status
        except Exception as e:
            if self._is_not_found_error(e):
                return None, "Not found"
            if self.verbose:
                print_error(f"Error checking status of '{instance_name}': {e}")
            return None, "Error"

    def get_instance_public_ip(self, instance_name: str, zone: str) -> Optional[str]:
        """Retrieves the public IP address of a specific instance."""
        if not instance_name or not zone:
            return None
        try:
            req = compute_v1.GetInstanceRequest(project=self.project_id, zone=zone, instance=instance_name)
            instance = self.instances_client.get(request=req)
            if instance.network_interfaces:
                nic = instance.network_interfaces[0]
                if nic.access_configs and len(nic.access_configs) > 0:
                    return nic.access_configs[0].nat_i_p
        except Exception as e:
            if self.verbose:
                print_error(f"Error retrieving public IP of '{instance_name}': {e}")
        return None

    def _prepare_startup_script(self) -> Optional[str]:
        """Reads 'startup.sh', injects WireGuard peers."""
        try:
            script_dir = os.path.dirname(__file__)
            script_path = os.path.abspath(os.path.join(script_dir, "..", "startup.sh"))
            if not os.path.exists(script_path):
                print_error(f"Startup script not found: {script_path}")
                return None

            with open(script_path, "r") as f:
                template = f.read()

            # Prepare peer configurations
            peer_configs = ""
            for client in self.config.wireguard_clients:
                peer_configs += f'wg set wg0 peer {client.public_key} allowed-ips {client.allowed_ip}\n'

            # Replace placeholders
            startup_script = template.replace("# PEER_CONFIGS_PLACEHOLDER", peer_configs).strip()
            return startup_script
        except Exception as e:
            if self.verbose:
                print_error(f"Failed to prepare startup script: {e}")
            return None

    def deploy_vpn(self, region: str, zone: str, rotation_suffix: str = None) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """
        Creates a new instance in the given region/zone.
        Returns (name, region, zone, public_ip) or (None, None, None, None) on failure.
        """
        startup_script = self._prepare_startup_script()
        if not startup_script:
            return None, None, None, None

        # Base instance name
        instance_name = f"{self.config.instance_prefix}-{region}-{zone.split('-')[-1]}"
        
        # Append suffix if provided
        if rotation_suffix:
            instance_name = f"{instance_name}-{rotation_suffix}"
        machine_type_uri = f"projects/{self.project_id}/zones/{zone}/machineTypes/{self.config.machine_type}"
        source_image_uri = "projects/debian-cloud/global/images/debian-12-bookworm-v20240415"
        disk_type_uri = f"projects/{self.project_id}/zones/{zone}/diskTypes/pd-balanced"
        network_uri = f"projects/{self.project_id}/global/networks/default"

        instance_resource = compute_v1.Instance(
            name=instance_name,
            machine_type=machine_type_uri,
            can_ip_forward=True,
            tags=compute_v1.Tags(items=list(self.config.machine_tags)),
            disks=[
                compute_v1.AttachedDisk(
                    boot=True,
                    auto_delete=True,
                    type_="PERSISTENT",
                    initialize_params=compute_v1.AttachedDiskInitializeParams(
                        source_image=source_image_uri,
                        disk_size_gb=10,
                        disk_type=disk_type_uri
                    )
                )
            ],
            network_interfaces=[
                compute_v1.NetworkInterface(
                    network=network_uri,
                    access_configs=[
                        compute_v1.AccessConfig(
                            name="External NAT",
                            type_="ONE_TO_ONE_NAT",
                            network_tier=self.config.network_tier.upper()
                        )
                    ]
                )
            ],
            metadata=compute_v1.Metadata(
                items=[compute_v1.Items(key="startup-script", value=startup_script)]
            )
        )

        try:
            if self.verbose:
                print_info(f"Deploying instance '{instance_name}' in zone '{zone}'...")

            req = compute_v1.InsertInstanceRequest(
                project=self.project_id,
                zone=zone,
                instance_resource=instance_resource
            )
            
            success = self._execute_instance_operation(
                lambda: self.instances_client.insert(request=req),
                zone,
                "Instance Creation"
            )
            
            if not success:
                return None, None, None, None

            public_ip = self.get_instance_public_ip(instance_name, zone)
            if not public_ip:
                print_warning(f"Instance '{instance_name}' deployed but public IP not found immediately.")
                
            return instance_name, region, zone, public_ip

        except Exception as e:
            if self.verbose:
                print_error(f"Failed to deploy '{instance_name}': {e}")
            return None, None, None, None

    def delete_vpn_server(self, instance_name: str, zone: str) -> bool:
        """Deletes the specified instance."""
        if not instance_name or not zone:
            print_warning("No instance/zone provided to delete.")
            return True
            
        return self._execute_instance_request(
            compute_v1.DeleteInstanceRequest(
                project=self.project_id,
                zone=zone,
                instance=instance_name
            ),
            self.instances_client.delete,
            zone,
            "Instance Deletion",
            f"Instance '{instance_name}' not found (already deleted)."
        )

    def turn_off_vpn(self, instance_name: str, zone: str) -> bool:
        """Stops the specified instance."""
        if not instance_name or not zone:
            print_warning("No instance/zone to stop.")
            return True
            
        return self._execute_instance_request(
            compute_v1.StopInstanceRequest(
                project=self.project_id,
                zone=zone,
                instance=instance_name
            ),
            self.instances_client.stop,
            zone,
            "Instance Stop",
            f"Instance '{instance_name}' not found (already stopped?)."
        )

    def turn_on_vpn(self, state: VPNState,
                    region_to_use: Optional[str],
                    zone_to_use: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """
        Starts an existing instance if it matches the region/zone in state, or deploys a new one.
        Returns (instance_name, region, zone, public_ip).
        """
        region = region_to_use or state.region
        zone = zone_to_use or state.zone
        if not region or not zone:
            print_error("Cannot determine region/zone to start VPN.")
            return None, None, None, None

        # If current state has instance, try starting it
        if state.instance_name and state.region == region and state.zone == zone:
            if self.verbose:
                print_info(f"Starting existing instance '{state.instance_name}' in zone '{zone}'...")
            try:
                req = compute_v1.StartInstanceRequest(
                    project=self.project_id, zone=zone, instance=state.instance_name
                )
                success = self._execute_instance_operation(
                    lambda: self.instances_client.start(request=req),
                    zone,
                    "Instance Start"
                )
                
                if success:
                    ip = self.get_instance_public_ip(state.instance_name, zone)
                    return state.instance_name, region, zone, ip
                return None, None, None, None
                
            except Exception as e:
                if self._is_not_found_error(e):
                    print_error(f"Instance '{state.instance_name}' not found; will deploy a new one.")
                else:
                    if self.verbose:
                        print_error(f"Failed to start '{state.instance_name}': {e}")
                    return None, None, None, None

        # If zone changed or instance not found, delete old if needed
        if state.instance_name and (state.zone != zone or state.region != region):
            self.delete_vpn_server(state.instance_name, state.zone or "")

        return self.deploy_vpn(region, zone)

    def get_server_public_key(self,
                              instance_name: str,
                              zone: str,
                              max_retries: int = 30,
                              retry_interval: int = 10) -> Optional[str]:
        """Fetches the WireGuard public key from serial console output."""
        if not instance_name or not zone:
            print_warning("No instance/zone to retrieve public key from.")
            return None

        pattern = r"\[PUBLIC_KEY\] ([A-Za-z0-9+/]{43}=)"
        req = compute_v1.GetSerialPortOutputInstanceRequest(
            project=self.project_id, zone=zone, instance=instance_name, port=1
        )
        
        for attempt in range(max_retries):
            try:
                response = self.instances_client.get_serial_port_output(request=req)
                if response and response.contents:
                    match = re.search(pattern, response.contents)
                    if match and len(match.group(1)) == 44 and match.group(1).endswith("="):
                        return match.group(1)
                        
                if attempt < max_retries - 1:
                    time.sleep(retry_interval)
            except Exception as e:
                if self.verbose:
                    print_warning(f"Attempt {attempt+1}, error: {e}")
                
        if self.verbose:
            print_error("Public key not found after max retries.")
        return None

    def get_next_rotation_number(self, region: str, zone: str) -> int:
        """Finds the next available rotation number for the given region/zone."""
        base_name = f"{self.config.instance_prefix}-{region}-{zone.split('-')[-1]}"
        pattern = re.compile(f"{re.escape(base_name)}-rotate(\\d+)")
        
        highest_number = 0
        
        try:
            req = compute_v1.ListInstancesRequest(project=self.project_id, zone=zone)
            for instance in self.instances_client.list(request=req):
                match = pattern.match(instance.name)
                if match:
                    number = int(match.group(1))
                    highest_number = max(highest_number, number)
                    
            return highest_number + 1
        except Exception as e:
            if self.verbose:
                print_warning(f"Failed to list instances for rotation number check: {e}")
            return 1  # Default to 1 if we can't determine
    
    def _wait_for_operation(self,
                            operation,
                            zone: str,
                            description: str,
                            timeout_sec: int = 300) -> bool:
        """Blocks until the given operation is DONE or times out."""
        if not operation:
            raise ValueError(f"Cannot wait for {description}, operation is None.")

        op_name = operation.name
        if self.verbose:
            print_info(f"Waiting for {description} '{op_name}' to complete...")

        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            try:
                if zone:
                    # Zonal operation
                    wait_req = compute_v1.WaitZoneOperationRequest(
                        project=self.project_id, zone=zone, operation=op_name
                    )
                    final_op = self.zone_operations_client.wait(request=wait_req)
                else:
                    # Global operation
                    wait_req = compute_v1.WaitGlobalOperationRequest(
                        project=self.project_id, operation=op_name
                    )
                    final_op = self.global_operations_client.wait(request=wait_req)

                if final_op.status == compute_v1.Operation.Status.DONE:
                    if final_op.error and final_op.error.errors:
                        codes = [err.code for err in final_op.error.errors]
                        msgs = [err.message for err in final_op.error.errors]
                        raise RuntimeError(f"{description} '{op_name}' failed: {codes} - {msgs}")
                    if self.verbose:
                        print_success(f"{description} '{op_name}' completed.")
                    return True
            except Exception as e:
                if self._is_not_found_error(e):
                    if self.verbose:
                        print_warning(f"{description} operation not found yet. Will retry...")
                else:
                    raise e
            time.sleep(3)

        raise TimeoutError(f"{description} '{op_name}' did not finish within {timeout_sec} seconds.")
    
    def _is_not_found_error(self, error: Exception) -> bool:
        """Check if an exception is a 'not found' or '404' error."""
        err_msg = str(error).lower()
        return "not found" in err_msg or "404" in err_msg
    
    def _execute_instance_operation(self, operation_func, zone: str, description: str) -> bool:
        """Execute an instance operation and wait for it to complete."""
        try:
            op = operation_func()
            self._wait_for_operation(op, zone=zone, description=description)
            return True
        except Exception as e:
            if self.verbose and not self._is_not_found_error(e):
                print_error(f"Failed to execute {description}: {e}")
            return False
    
    def _execute_instance_request(self, request: Any, client_method, zone: str, 
                                 description: str, not_found_msg: str) -> bool:
        """Execute an instance request with standard error handling."""
        try:
            if self.verbose:
                print_info(f"Executing {description}...")
                
            op = client_method(request=request)
            self._wait_for_operation(op, zone=zone, description=description)
            return True
        except Exception as e:
            if self._is_not_found_error(e):
                if self.verbose:
                    print_warning(not_found_msg)
                return True
            if self.verbose:
                print_error(f"Failed to execute {description}: {e}")
            return False

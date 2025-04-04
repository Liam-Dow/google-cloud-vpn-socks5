# VPN Manager

A command-line tool for deploying, managing, and connecting to a personal WireGuard VPN using Google Compute Engine.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

* **Seriously Good Performance:** By default, the VPN server uses Google's **Premium Tier network**. This often means your traffic takes a more direct, less congested path across Google's private backbone, effectively bypassing potential slowdowns on your local ISP's network or the public internet. In my own testing, I've actually seen *faster* speeds to some services when connected through my GCP WireGuard VPN compared to my direct connection! This is pretty unusual for VPNs, which typically add latency. *(You can switch to the Standard Tier to potentially run it for free, see the [How to Run for Free](#how-to-run-vpn-manager-for-free-using-gcp-free-tier) section).*

* **You Control the Keys (Better Security):** WireGuard itself uses modern, strong cryptography. With this setup, the private keys for the VPN server are generated *on the server* when it's first created and aren't shared anywhere. *You* hold the private key for your client device. Unlike commercial VPNs where you trust the provider with server access and potentially logs, here *you* are the provider. Nobody else can decrypt your tunnel traffic because nobody else has the keys.

* **Surprisingly Cheap (Often Free!):** Commercial VPNs usually involve a fixed monthly or annual subscription. GCP bills based on *what you use*.
*   Running the default `e2-micro` server 24/7 for a whole month in a paid region only costs around **$4-5 USD** (as of early 2024).
*   Since you likely won't run it 24/7 (the script makes it easy to start/stop!), your actual cost could be **$1 or less per month**, maybe even just pennies.
*   If you follow the **Free Tier** guidelines (see section below), it can be completely **free**.
* **Caveat:** GCP charges for *egress* (data leaving Google Cloud). You get a generous free amount each month (especially within North America or using the Free Tier regions). If you consistently transfer *huge* amounts of data (like >1 TB/month) *out* of GCP through the VPN, you might see small egress charges. Check the [GCP Network Pricing page](https://cloud.google.com/vpc/network-pricing) for details, but even then, it's usually very competitive. For most personal use, cost is minimal.

* **Connect Multiple Devices:** The setup easily supports adding multiple clients (peers). Add your laptop, your phone, maybe even your home router if it supports WireGuard client configuration. Just generate a key pair for each device and add them to the `wireguard_clients` list in `config.json` *before* deploying or restarting the server.

* **Secure Access to Your GCP Stuff (Advanced):** If you use GCP for other projects, you could potentially configure this VPN server to allow secure access (via internal IPs) to your other private cloud resources using GCP's firewall rules, without needing bastion hosts or IAP tunnels for everything.



# Get Started
## Prerequisites

Before you start, make sure you have the following:

1.  **Google Cloud Project:** You'll need a GCP project with billing enabled. (Don't worry, you'll be able to run it at zero cost or at most a few dollars if you want to use Google's premium network. See [How to Run for Free](#how-to-run-vpn-manager-for-free-using-gcp-free-tier)).
2.  **Enable GCP APIs:** Ensure the **Compute Engine API** is enabled in your GCP project. [Link to API Library.](https://console.cloud.google.com/projectselector/apis/library/compute.googleapis.com?invt=AbtUcQ)
3.  **`gcloud` CLI:** Install [gcloud cli](https://cloud.google.com/sdk/docs/install). After installation, make sure you're authenticated by running `gcloud auth login`.
4.  **Python:** This project was developed on Python 3.13, but Python 3.12 and above should be okay.
5.  **WireGuard Tools:** You need the WireGuard command-line tools installed on your local machine (the one you'll run this script from).
    *   **macOS:** Use [Homebrew](https://brew.sh/) (`brew install wireguard-tools`). The default config path is `/opt/homebrew/etc/wireguard/`.
    *   **Linux:** Install `wireguard-tools` using your favourite package manager (e.g., `sudo apt install wireguard-tools`, `sudo yum install wireguard-tools`). The default config path is `/etc/wireguard/`.
6.  **`sudo` Privileges:** The script uses `sudo wg-quick up` and `sudo wg-quick down` to manage the local VPN connection. You'll either need to run the script itself with `sudo` (`sudo python vpn_manager.py`) or be prepared to enter your password when prompted.

> **Operating System Note**: I developed this on macOS, but it will work on Linux too. Windows will require some tweaks (especially around paths and the `wg-quick` commands), which I haven't tested yet, but I intend to add support in the future. In the meantime consider using Windows Subsystem for Linux (wsl).

## Configuring your GCP Project

1.  **Allow WireGuard Traffic**
    For the VPN server to receive connections, you'll need to create a firewall rule. The script assumes you have one that allows inbound UDP traffic on port 51820 to instances tagged with `wireguard` (this tag is set in `config.json` and applied by the script).

    You can create this rule using the following `gcloud` command line:

    ```bash
    gcloud compute firewall-rules create allow-wireguard \
    --project=YOUR_GCP_PROJECT_ID \
    --action=ALLOW \
    --direction=INGRESS \
    --rules=udp:51820 \
    --target-tags=wireguard
    ```
    *(Replace `YOUR_GCP_PROJECT_ID` with your actual project ID)*.

2.  **Increase default MTU**
    Google Cloud's default maximum transmission unit (MTU) is set to 1460. The standard MTU size for regular internet traffic is 1500. Ultimately for most users this will have limited impact but it increases the liklihood of packet fragmentation and reduced performance. See (## MTU Configuration) for more details.

    Run the following `gcloud` command to update the default MTU:
    ```bash
    gcloud compute networks update default \
    --project=YOUR_GCP_PROJECT_ID \
    --mtu=1500
    ```

## Installation

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/Liam-Dow/vpn-manager.git
    cd vpn-manager
    ```

2.  **Install Dependencies:**
    ```bash
    # This installs the InquirerPy library used for the interactive TUI menu.
    pip install -r requirements.txt
    ```

3.  **Configure the Application (`config.json`):**
    ```bash
    # Create your personal configuration file from the example
    cp example.config.json config.json

    # Now, edit config.json using your preferred text editor
    nano config.json
    ```
    I'd recommend keeping most settings at their defaults. The only **required** edits are:
    *   **`project_id`**: Must match your GCP project ID exactly.
    *   **`wireguard_clients`**: You *must* define at least one client device here.
    *   Generate the `"public_key"` in the next step.
    *   Choose a unique `"allowed_ip"` (e.g., `10.0.0.2/32`). The server uses `10.0.0.1`.
    *   **`wireguard_config_file`**: Update this path to point to the *actual* WireGuard config file on your local machine (e.g., `/opt/homebrew/etc/wireguard/wg0.conf` or `/etc/wireguard/wg0.conf`).

    The commented example below explains each field:
    ```json
    {
        "project_id": "your-gcp-project-id", // REQUIRED: Your Google Cloud project ID
        "network_tier": "PREMIUM",         // "PREMIUM" (default) or "STANDARD" (for free tier)
        "machine_tags": ["wireguard"],     // Tags for firewall rule
        "instance_prefix": "vpn-server",   // Base name for VM instance
        "machine_type": "e2-micro",        // GCP machine type (free tier eligible)

        "wireguard_port": 51820,           // WireGuard UDP port
        "wireguard_clients": [             // REQUIRED: List of devices
            {
                "name": "your-device-name", // Friendly name
                "public_key": "YOUR_CLIENT_PUBLIC_KEY_HERE", // REQUIRED: Generate in next step
                "allowed_ip": "10.0.0.2/32" // REQUIRED: Unique internal IP for this client
            }
            // Add more clients if needed
        ],

        // REQUIRED: Path to your local WireGuard config file (e.g., wg0.conf)
        "wireguard_config_file": "/opt/homebrew/etc/wireguard/wg0.conf",

        // Status checking settings
        "ip_info_service": "http://ipinfo.io/json",
        "connectivity_check_ip": "8.8.8.8"
    }
    ```
    > **Important:** The script expects `config.json` to be located in the same directory you run `vpn_manager.py` from (the project root). Don't move it. `vpn_state.json` is also expected here; if missing, it will be created automatically on first run. A missing `config.json`, however, will cause an error. An example state file (`vpn_state.example.json`) is provided to show the structure.


### Generating Your Client Key Pair

Your local device (the "client") needs its own WireGuard keys. You'll put the **public** key into `config.json` above. Keep the **private** key safe – you'll need it for the next step.

1.  **Open your terminal.**
2.  **Generate the keys:** We'll name them `client.key` and `client.pub` below, but feel free to choose different names. While you can generate/store keys anywhere, I'd recommend keeping them in the standard WireGuard config directory:

    ```bash
    # macOS:
    sudo sh -c 'wg genkey | tee /opt/homebrew/etc/wireguard/client.key | wg pubkey > /opt/homebrew/etc/wireguard/client.pub'

    # Linux:
    # sudo sh -c 'wg genkey | tee /etc/wireguard/client.key | wg pubkey > /etc/wireguard/client.pub'
    ```

3.  **Secure the private key:** Ensure only root can read it - it's what keeps your VPN tunnel secure!

    ```bash
    # macOS:
    sudo chmod 600 /opt/homebrew/etc/wireguard/client.key

    # For Linux
    # sudo chmod 600 /etc/wireguard/client.key
    ```

4.  **Get the public key:** Display the public key so you can copy it.

    ```bash
    # macOS:
    sudo cat /opt/homebrew/etc/wireguard/client.pub

    # Linux:
    # sudo cat /etc/wireguard/client.pub
    ```
    Copy the output string (ends with `=`). Go back and **paste this public key** into the `"public_key"` field within the `wireguard_clients` list in your `config.json`.

### Creating Your Local WireGuard Config File

Now we'll create the actual WireGuard config file so you're able to connect to your VPN. This file will need the **private key**.

1.  **Create and Edit the Config File:** Use `sudo` with your text editor. Ensure the filename matches `wireguard_config_file` in `config.json`.

    ```bash
    # macOS:
    sudo nano /opt/homebrew/etc/wireguard/wg0.conf

    # Linux:
    # sudo nano /etc/wireguard/wg0.conf
    ```

2.  **Paste and Edit the Template:** Copy the template below, paste it into the editor, and update:

    ```ini
    [Interface]
    # ---> PASTE your client's PRIVATE key here (from client.key)
    PrivateKey = PASTE_YOUR_CLIENT_PRIVATE_KEY_HERE

    # ---> SET your client's internal IP (must match 'allowed_ip' from config.json)
    Address = 10.0.0.2/24

    # Optional: DNS servers (Google's public DNS shown)
    DNS = 8.8.8.8, 8.8.4.4

    # Optional: Client MTU (Recommended value)
    MTU = 1380

    [Peer]
    # Server's public key (Script updates this - leave placeholder)
    PublicKey = PLACEHOLDER_SERVER_PUBLIC_KEY

    # Route all traffic through VPN
    AllowedIPs = 0.0.0.0/0

    # Server IP:Port (Script updates this - leave placeholder)
    Endpoint = placeholder.example.com:51820
    ```

    *   Replace `PASTE_YOUR_CLIENT_PRIVATE_KEY_HERE` with the content of your `client.key` file (use `sudo cat /opt/homebrew/etc/wireguard/client.key` or `sudo cat /etc/wireguard/client.key` to view it).
    *   Ensure the `Address` matches the IP part of `allowed_ip` from `config.json`.
    *   Leave `PublicKey` and `Endpoint` as placeholders; **VPN Manager will set these and keep them up to date for you moving forward**

3.  **Save and Exit:** (`Ctrl+x` then `y` in `nano`).

4.  **Secure the Config File:**

    ```bash
    # macOS:
    sudo chmod 600 /opt/homebrew/etc/wireguard/wg0.conf

    # Linux:
    # sudo chmod 600 /etc/wireguard/wg0.conf
    ```

    ***Running vpn_manager.py:***

That's all the manual work done now and you should be ready to deploy, connect and manage your own private-dedicated-enterprise-grade-low-cost VPN going forward!

Run the application from the project directory using:

```bash
# Run with sudo to avoid password prompts for wg-quick
sudo python vpn_manager.py

# Or run without sudo and you'll be prompted for sudo password when needed
python vpn_manager.py
```

The application presents an interactive menu. The menu options will automaticall update to match your current state. Full list of options includes:

    *   **Deploy & Connect / Deploy Only:** Spin up a new VPN server on GCP (and optionally connect right away).
    *   **Start VPN Server:** Start an existing, stopped VPN server instance.
    *   **Stop VPN Server / Disconnect & Stop:** Stop the running GCP instance (saves some pennies when not in use).
    *   **Delete VPN Server:** Permanently remove the instance and associated resources from GCP.
    *   **Connect / Disconnect:** Manage your local VPN connection to the server.
    *   **Run Status Check:** Perform checks on your connection, GCP instance, and configuration sync.
    *   **View WireGuard Config:** Display the contents of your local `wg0.conf` file (Note this will print your local `wg0.conf` private key to your terminal)


Once you connect to your VPN the menu will update to display your new public IP address, see example below:



**Run Status Check:** For a more detailed look, choose the "Run Status Check" option from the menu. This performs several checks:
    *   Confirms internet connectivity.
    *   Checks the GCP instance status directly via `gcloud`.
    *   Verifies the WireGuard interface is active locally using `wg show`.
    *   Checks your current public IP address using an external service.
    *   Compares the server IP in your local WireGuard config file (`wg0.conf`) against the actual GCP instance IP fetched via `gcloud`.

If the main menu shows `Connected` and your public IP matches the VPN server's location, you're generally good to go! The status check helps diagnose issues if things aren't working as expected.


# Understanding the Google Cloud Deployment

Instead of messing around with creating and maintaining custom virtual machine images, VPN Manager takes a simpler approach. When you choose to deploy, it spins up a standard, fresh Debian 12 VM on GCP and then runs a setup script (`startup.sh`) automatically when the VM first boots.

This method has several advantages:

1.  **No Image Maintenance:** You don't need to build, maintain or pay for a custom machine image. The script handles everything.
2.  **Transparency:** You can see exactly what commands are run to configure your VPN server by looking at the `startup.sh` file in the repository.
3.  **Always Up-to-Date:** It always starts with the latest official Debian 12 image provided by Google, ensuring you get recent OS patches.
4.  **Automatic Configuration:** WireGuard, networking, firewall rules and server private keys are all set up from scratch for each new deployment.

### Inside the Startup Script (`startup.sh`)

Here's a step-by-step look at what the `startup.sh` script does to turn that basic Debian VM into your WireGuard VPN server:

1.  **Install Software (`apt-get install ...`):**
    *   **What:** It first updates the package list and then installs the necessary tools: `wireguard` and `ufw` (Uncomplicated Firewall)
    *   **Why:** wireguard of course provides the core VPN functionality, but ufw is technically not needed and effectively redundant due to the GCP firewall rules. However it is needed if you want to run the MTU benchmarking tool, and considering it's a 750kb packagae - it's easier just to keep it one-size fits all. 

2.  **Enable IP Forwarding (`sed ... sysctl.conf`, `sysctl -p`):**
    *   **What:** It modifies the system's network settings (`/etc/sysctl.conf`) to allow the server to forward network packets between different network interfaces (specifically, between the internet-facing one and the WireGuard tunnel). `sysctl -p` applies the change immediately.
    *   **Why:** For the VPN to work, the server needs to act like a router, taking packets from your VPN client (via the `wg0` tunnel interface) and forwarding them out to the internet (via the main network interface), and vice-versa. This setting enables that core routing function.

3.  **Generate Server Keys (`wg genkey`, `wg pubkey`, `chmod`):**
    *   **What:** It creates a directory (`/etc/wireguard/keys`) and then generates a unique private and public key pair for the WireGuard *server*, but *only if* a private key (`server.key`) doesn't already exist. It then sets strict file permissions (`chmod 600`) on the private key.
    *   **Why:** WireGuard relies on public-key cryptography. The server needs its own key pair. Generating it only if it's missing makes the script safe to run even if the VM restarts.

4.  **Log Server Public Key (`echo ... $(cat ...)`):**
    *   **What:** It prints the server's *public* key to the GCP serial console.
    *   **Why:**  The `vpn_manager.py` script running on your local machine needs to know the server's public key to configure your local WireGuard client correctly. It fetches this key by reading the serial console output after deployment enabling it to be an automated process. 

5.  **Configure WireGuard Interface (`wg0`):**
    *   **a) Find Network Interface (`ip route ... awk ...`):** It figures out the name of the VM's primary network interface (`ens4` seems to always be the default for micro-e2, but I believe it can change from time to time).
    *   **Why:** We need this so we know where to send traffic destined for the internet.
    *   **b) Create `wg0` (`ip link add ...`):** Creates the virtual network interface for WireGuard, named `wg0`.
    *   **Why:** This is the actual tunnel interface where VPN traffic will flow.
    *   **c) Set Key & Port (`wg set wg0 ...`):** Tells the `wg0` interface to use the server's private key generated earlier and to listen for incoming VPN connections on UDP port 51820.
    *   **Why:** Links the key to the interface and sets the listening port.
    *   **d) Assign IP, Set MTU, Activate (`ip address add ...`, `ip link set mtu ...`, `ip link set up ...`):** Assigns the internal IP address `10.0.0.1` to the server within the VPN tunnel, sets the MTU (Maximum Transmission Unit) to `1420` (20 bytes for wireguard headers + 20 bytes for ipv4 + 20 bytes overhead for your router/ISP - 1500 standard MTU), and activates the `wg0` interface.
    *   **Why:** The server needs an IP within the VPN subnet (`10.0.0.0/24`). Setting the MTU can help avoid packet fragmentation issues (see [Advanced: MTU Configuration](#advanced-mtu-configuration-optional)). Activating the interface makes it ready to handle traffic.
    *   **e) Setup NAT & Forwarding (`iptables ...`):** These two `iptables` rules are critical for internet access through the VPN.
    *   `iptables -A FORWARD -i wg0 -j ACCEPT`: Allows packets arriving on the `wg0` interface to be forwarded elsewhere (specifically, out to the internet via the main interface found earlier).
    *   `iptables -t nat -A POSTROUTING -o "$IFACE" -j MASQUERADE`: This ensure all traffic leaving the server (that originated from your VPN client) look like it came *from* the server's public IP address, rather than the client's internal `10.0.0.x` IP.
    *   **Why:** Without forwarding, packets stop at the server, so without MASQUERADE, the return traffic from the internet wouldn't know how to get back to your client via the tunnel!

6.  **Configure Firewall (`ufw ...`):**
    *   **What:** It configures the `ufw` firewall to allow incoming traffic on UDP port 51820 (for WireGuard) and TCP port 22 (for SSH access, important for debugging!). It then enables the firewall, applying the rules. `--force` prevents it from asking for confirmation.
    *   **Why:** We need to explicitly allow the VPN traffic through the server's own firewall. Allowing SSH is good practice for server access. Enabling the firewall secures the server by blocking other unwanted incoming connections by default.

7.  **Add Peers (`# PEER_CONFIGS_PLACEHOLDER`):**
    *   **What:** `vpn_manager.py` updates this line with your client `wg set wg0 peer <CLIENT_PUBLIC_KEY> allowed-ips <CLIENT_ALLOWED_IP>` commands for each client defined in your `config.json`.
    *   **Why:** This is how the server knows about *your* client devices and allows you to connect to the VPN - but nobody else.

8.  **Log Final Status (`wg show wg0`):**
    *   **What:** Displays the current status of the `wg0` interface in the logs.
    *   **Why:** Useful for confirmation and debugging – you can check the serial console log to see if the interface came up and if peers were added correctly.


## MTU Configuration

Using the wrong MTU size can have a fairly significant impact on your the performance and stability of your VPN. WireGuard needs to encapsulate your data, which adds extra bytes to each packet increasing the total overhead. If the resulting packet size is too large for any link between you and the VPN server, packets can get fragmented or dropped, leading to slow speeds or connection issues.

During my testing, I found the following settings worked well for GCP and my typical home network. They should be a good starting point for most people, but the optimal values will completely depend on your router, your ISP, or the type of client you're using.

My ra

    *   **GCP VPC Network:** Leave at the default `1460`. GCP handles underlying network complexities, so tweaking this usually isn't necessary.
    *   **WireGuard Server (`wg0` interface on the VM):** The `startup.sh` script sets `MTU = 1420` on the server's `wg0` interface. This leaves 40 bytes of overhead for the outer IP/UDP headers added by WireGuard.
    *   **WireGuard Client/Peer (Your local machine):** You might need to manually add `MTU = 1380` under the `[Interface]` section of your local `wg0.conf` file. This accounts for the overhead added by WireGuard *and* potential overhead on your local network connection.

    **How the script handles it:** The `startup.sh` script sets the server's interface MTU. You might need to manually add the `MTU = 1380` line to your local `wg0.conf` file if you experience performance issues or connection drops, especially with certain types of traffic.

If you run into problems, experimenting with the client MTU (lowering it slightly, e.g., `1360`, `1340`) is often the first step. There are guides online for finding your optimal path MTU if you need to dive deeper, but `1380` is often a safe bet.


# How to Run VPN Manager for Free (Using GCP Free Tier)

Google Cloud offers an "Always Free" tier which is fairly limited for most use-cases to be honest but this project can fit well within the boundaries of that tier if you would prefer to keep it 100% free. 

To stay within the free tier make sure you follow the below requirements:

1.  **Machine Type:** Use `e2-micro`. This is already the **default** setting (`"machine_type": "e2-micro"`) in `config.json`, and honestly it's just a waste of money to increase this even if you want to maximise your bandwidth - the limiting factor will be your ISP's copper wires under your feet and how close you are to one of Google Points of Presence much more so than how fast your server can encrypt traffic.

2.  **Region:** The VM must be located in one of the following US regions:
    *   `us-west1` (Oregon)
    *   `us-central1` (Iowa)
    *   `us-east1` (South Carolina)
    When you deploy, the script will ask you to select a region – just choose one of these.
3.  **Network Tier:** You must use the **Standard** network tier. The default in `config.json` is `"PREMIUM"`. You'll need to **edit your `config.json`** and change:
    ```json
    "network_tier": "PREMIUM",
    ```
    to:
    ```json
    "network_tier": "STANDARD",
    ```
    Standard tier might have slightly higher latency than Premium, but it's free!
4.  **Egress Traffic:** The free tier includes 1 GB of network egress *per month* (pooled across eligible services) to destinations *outside* North America (traffic within North America is generally free or cheaper). 1 GB is usually enough for typical browsing, but keep it in mind if you plan heavy downloads/streaming through the VPN to locations outside North America.

    **In summary:** Use the default `e2-micro`, deploy in `us-west1`, `us-central1`, or `us-east1`, change `network_tier` to `STANDARD` in `config.json`, and keep an eye on your egress if doing heavy lifting outside North America.

For the full details and latest limits, check the official [Google Cloud Free Tier documentation](https://cloud.google.com/free/docs/gcp-free-tier).

## Security Considerations

    *   The VPN server's WireGuard port (51820 UDP by default) is exposed to the internet via the GCP firewall rule. Only clients with a known public key (configured on the server via `config.json`) and the correct server public key can establish a connection.
    *   WireGuard uses public-key cryptography. **Keep your client private key secure!** You can rotate the keys easily when needed by creating a new key pair and updating the config.json and wg0.conf when needed. 
    *   The server's private key resides only on the GCP VM instance. It is never exposed and a new private key is generated for every deployment. 
    *   Consider limiting the GCP firewall rule (`allow-wireguard`) source IP ranges if you only want to connect from a known static IP.
    *   The `startup.sh` script enables `ufw` on the VM, blocking incoming traffic except for WireGuard (51820/udp) and SSH (22/tcp). This extra layer is required to run the MTU optimisation script, but is largely redundant for the VPN traffic itself - but it's just easier to have a 1 size fits all build.

## Troubleshooting

    *   **Deployment Fails:**
    *   Check `gcloud` authentication (`gcloud auth list`).
    *   Verify your `project_id` in `config.json` is correct.
    *   Ensure the Compute Engine API is enabled in your GCP project.
    *   Check the GCP Console for any errors during VM creation.
    *   **Server Deploys but Doesn't Work / Key Fetch Fails:**
    *   The `startup.sh` script might have failed. Check the VM's serial console output in the GCP Console (Compute Engine -> VM Instances -> Click your instance -> View Serial port 1 logs). Look for errors after the `[INFO] Starting WireGuard manual setup...` line.
    *   Ensure the `wireguard` tag is correctly applied to the instance and the `allow-wireguard` firewall rule exists and is enabled.
    *   **Connect Fails / No Internet Through VPN:**
    *   Verify the `Endpoint` IP address and `PublicKey` in your local `wg0.conf` file match the server's current public IP and the public key shown in the serial console log / `vpn_state.json`. Use "Run Status Check" to verify.
    *   Check if the WireGuard service is running on the server (you might need to SSH into the VM and run `sudo wg show`).
    *   Ensure IP forwarding is still enabled on the server (`cat /proc/sys/net/ipv4/ip_forward` should output `1`).
    *   Check `ufw` status on the server (`sudo ufw status`) to ensure 51820/udp is allowed.
    *   Try adjusting the MTU setting in your local `wg0.conf` (see [Advanced: MTU Configuration](#advanced-mtu-configuration-optional)).
    *   **"wg-quick: `wg0` already exists" Errors:** Your local WireGuard interface might already be up. Use the "Disconnect" option in the script or run `sudo wg-quick down wg0` (or your config file name) manually before trying to connect again.
    *   **Permission Errors:** If you see errors related to `sudo` or `wg-quick`, try running the script with `sudo python vpn_manager.py`.
    *   **State Mismatch:** If the script's state seems out of sync with GCP (e.g., it thinks a server exists when it doesn't), the "Run Status Check" option is designed to detect and correct this by comparing local state with `gcloud describe` output.

## Project Structure

- `vpn_manager.py` - Main entry point for the application
- `vpn_manager/` - Python package containing the core functionality
- `startup.sh` - Script that runs on the GCP VM to set up WireGuard
- `example.config.json` - Example configuration file
- `vpn_state.example.json` - Example state file
- `requirements.txt` - Python dependencies
- `LICENSE` - MIT License

## License

This project is licensed under the [MIT License](LICENSE). Feel free to use, modify, and distribute it.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

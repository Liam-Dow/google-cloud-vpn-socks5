# VPN Manager

A command-line tool for deploying, managing, and connecting to a personal WireGuard VPN using Google Compute Engine.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

### **Why Use VPN Manager?**

VPN Manager helps you deploy and manage your own WireGuard server on Google Cloud. I've outlined some of the reasons why you might want to use this below, but firstly it's important to be aware of Google Cloud's egress costs on data - if you plan on downloading or streaming loads of TV shows - this is **probably** not the best option for you....

Why might you want to use this:

*   **You Control the Keys (Better Security):** WireGuard uses modern, strong crypto. You generate your client keys locally. The server keys are generated **ephemerally** on the server instance itself when it deploys. While ephemeral server keys could normally mean manually fetching the new public key each time, **VPN Manager automatically retrieves the server's public key** after deployment and updates your local configuration, keeping things seamless. And unlike commercial VPNs, *you're* the provider – no third party gets your keys or server access.

*   **Flexible Tunneling (Cost Control & Targeted Access):**
    *   **Full VPN Mode (`vpn`):** Routes *all* your device's traffic through the GCP server. Basically a full-fat VPN giving you maximum privacy. Just be mindful of GCP egress costs.
    *   **SOCKS5 Proxy Mode (`socks5`):** This mode configures WireGuard to only tunnel traffic heading *directly* to the VPN server's internal IP (`10.0.0.1/32`). The `startup.sh` script **automatically installs and runs `dante-server` (a SOCKS5 proxy)** on the server, configured to listen on `10.0.0.1:1080`. You can then point specific applications to use this proxy (like Firefox's network settings, or using `proxychains` in the terminal to force an app through it). Only the traffic *sent to the proxy* uses the encrypted WireGuard tunnel, drastically cutting down bandwidth and costs compared to the full VPN. This is a good option if you're wanting to keep data usage low or if you only want to change your public IP for certain sites or services.

*   **On-Demand & Easy to Use:** Need quick, temporary access from a different region or IP? VPN Manager lets you **spin up your dedicated VPN server or SOCKS5 tunnel in minutes without leaving your terminal**, use it to access a region-blocked webpage or sidestep a public API rate limit, and then **tear it down just as quickly** when you're done. The interactive menu makes managing the whole thing simple.

*   **Consumption-Based Compute Costs (No Subscriptions!):** Forget monthly VPN subscriptions you forget to cancel. GCP bills for the server compute time *only when it's running*. The base cost for the default `e2-micro` server is very low (potentially free under the Free Tier, or only a few dollars per month if run 24/7). Since the script makes it easy to start/stop, you **pay only for what you actually use**, perfect for when you only need a VPN for a quick task.

*   **Leverage Google's Network (Potential Performance Boost):** For traffic going to services near your GCP region, or even Google's own stuff, using Google's backbone (especially the **Premium Tier**) can sometimes give you better latency or download speeds than your regular internet, even with the VPN layer. In fact, during my tests, I frequently saw faster downloads from HuggingFace using the VPN vs my normal connection (guessing HF.co hosts some models on GCP).

*   **Secure Access to your GCP Resources:** If you have services running in a private GCP VPC **where a full bastion host or IAP setup seems like overkill**, this provides an easy way to securely access internal resources (like web UIs) without configuring complex SSH routing rules.

# Get Started
## Prerequisites

Before you start, make sure you have the following:

1.  **Google Cloud Project:** You'll need a GCP project with billing enabled.
2.  **Enable GCP APIs:** Ensure the **Compute Engine API** is enabled in your GCP project. [Link to API Library.](https://console.cloud.google.com/projectselector/apis/library/compute.googleapis.com?invt=AbtUcQ)
3.  **`gcloud` CLI:** Install [gcloud cli](https://cloud.google.com/sdk/docs/install). After installation, make sure you're authenticated by running `gcloud auth application-default login`.
4.  **Python:** Python 3.12 and above (minimum for current gcloud release)
5.  **WireGuard Tools:** You need the WireGuard command-line tools installed:
    *   **macOS:** Use [Homebrew](https://brew.sh/) (`brew install wireguard-tools`). The default config path is `/opt/homebrew/etc/wireguard/`.
    *   **Linux:** Install `wireguard-tools` using your favourite package manager (e.g., `sudo apt install wireguard-tools`, `sudo yum install wireguard-tools`). The default config path is `/etc/wireguard/`.
6.  **`sudo` Privileges:** The script uses `sudo wg-quick up` and `sudo wg-quick down` to manage the local VPN connection. You'll either need to run the script itself with `sudo` (`sudo python vpn_manager.py`) alternatively you can enter your password when prompted.

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
    git clone https://github.com/Liam-Dow/google-cloud-vpn-socks5
    cd vpn-manager
    ```

2.  **Install Dependencies:**
    ```bash
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


## License

This project is licensed under the [MIT License](LICENSE). Feel free to use, modify, and distribute it.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

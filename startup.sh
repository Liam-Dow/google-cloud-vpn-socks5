#!/bin/bash
set -e

# 1) Install wireguard + ufw + iptables if not already present
echo "[INFO] Updating package list..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y > /dev/null
echo "[INFO] Installing wireguard, ufw, iptables..."
apt-get install -y wireguard ufw iptables > /dev/null
echo "[SUCCESS] Packages installed."

# 2) Configure Sysctl Settings (IP Forwarding, TCP BBR, Buffer Sizes)
echo "[INFO] Configuring sysctl settings..."
cat << EOF > /etc/sysctl.d/99-vpn-optimizations.conf
# -- Network Forwarding --
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1

# -- TCP BBR Congestion Control --
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr

# -- TCP Buffer Sizes --
# Set core max limits (must be >= tcp max limits)
net.core.rmem_max=20971520
net.core.wmem_max=20971520
# Set TCP limits (min, default, max) - Using previously observed defaults
net.ipv4.tcp_rmem=4096 131072 20971520
net.ipv4.tcp_wmem=4096 16384 20971520
EOF
# Apply all settings from the file
sysctl -p /etc/sysctl.d/99-vpn-optimizations.conf > /dev/null
echo "[SUCCESS] sysctl settings applied."

# 3) Generate server private/public key (if not already existing)
echo "[INFO] Ensuring WireGuard server keys exist..."
mkdir -p /etc/wireguard/keys
if [ ! -f /etc/wireguard/keys/server.key ]; then
  echo "[INFO] Generating new server keys..."
  ( umask 077; wg genkey | tee /etc/wireguard/keys/server.key > /dev/null )
  cat /etc/wireguard/keys/server.key | wg pubkey > /etc/wireguard/keys/server.key.pub
  chmod 600 /etc/wireguard/keys/server.key
  echo "[SUCCESS] New server keys generated."
else
  echo "[INFO] Existing server keys found."
fi

# 4) Bring up wg0 interface
echo "[INFO] Configuring WireGuard interface (wg0)..."
IFACE=$(ip -o -4 route show to default | awk '{print $5}' | head -n 1)
if [ -z "$IFACE" ]; then
  echo "[ERROR] Could not determine default network interface. Exiting." >&2
  exit 1
fi
echo "[INFO] Default route interface detected as: $IFACE"
if ! ip link show wg0 > /dev/null 2>&1; then
  ip link add wg0 type wireguard
fi
wg set wg0 private-key /etc/wireguard/keys/server.key listen-port 51820
ip address add 10.0.0.1/24 dev wg0

# Set MTU based on my PPPoE (1492) - IPv4 overhead (60) -> 1432
echo "[INFO] Setting wg0 MTU to 1432..."
ip link set dev wg0 mtu 1432
echo "[INFO] Bringing wg0 interface up..."
ip link set wg0 up

echo "[INFO] Configuring iptables rules (NAT, Forwarding, MSS Clamp)..."
# Flush rules first (safer)
iptables -D FORWARD -i wg0 -j ACCEPT > /dev/null 2>&1 || true
iptables -t nat -D POSTROUTING -o "$IFACE" -j MASQUERADE > /dev/null 2>&1 || true
iptables -t mangle -D FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu > /dev/null 2>&1 || true
# Add rules
iptables -A FORWARD -i wg0 -j ACCEPT
iptables -t nat -A POSTROUTING -o "$IFACE" -j MASQUERADE
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
echo "[SUCCESS] iptables rules configured."

# 5) Set up UFW firewall rules
echo "[INFO] Configuring UFW firewall..."
# --- Explicitly allow forwarding in UFW config ---
echo "[INFO] Setting UFW default forward policy to ACCEPT..."
sed -i -e 's/DEFAULT_FORWARD_POLICY="DROP"/DEFAULT_FORWARD_POLICY="ACCEPT"/g' /etc/default/ufw
echo "[INFO] Ensuring UFW sysctl settings allow forwarding..."
sed -i -e 's/#net\/ipv4\/ip_forward=1/net\/ipv4\/ip_forward=1/g' /etc/ufw/sysctl.conf
sed -i -e 's/#net\/ipv6\/conf\/default\/forwarding=1/net\/ipv6\/conf\/default\/forwarding=1/g' /etc/ufw/sysctl.conf
sed -i -e 's/#net\/ipv6\/conf\/all\/forwarding=1/net\/ipv6\/conf\/all\/forwarding=1/g' /etc/ufw/sysctl.conf
# --- End UFW forwarding config ---

ufw allow 51820/udp > /dev/null
ufw allow 22/tcp > /dev/null
ufw default deny incoming > /dev/null
ufw default allow outgoing > /dev/null

# Reload UFW to apply changes and ensure it's enabled
echo "[INFO] Reloading and enabling UFW..."
ufw disable > /dev/null # Disable first to ensure reload takes effect
ufw --force enable > /dev/null
echo "[SUCCESS] UFW configured and enabled."

# 6) Install and configure Dante SOCKS5 proxy
# PROXY_INSTALL_PLACEHOLDER
echo "[INFO] Installing and configuring Dante SOCKS5 proxy..."
apt-get install -y dante-server > /dev/null

# Create Dante configuration
cat << EOF > /etc/danted.conf
# Dante SOCKS5 server configuration
logoutput: syslog
user.privileged: root
user.unprivileged: nobody

# Interface configuration - proper syntax for Dante
internal: 10.0.0.1 port=1080
external: $IFACE

# Authentication methods - enable 'none' method for both client and socks
clientmethod: none
socksmethod: none

# Client rules - allow connections from WireGuard subnet
client pass {
    from: 10.0.0.0/24 to: 0.0.0.0/0
    log: connect disconnect error
}

# Socks rules - allow connections from WireGuard subnet
socks pass {
    from: 10.0.0.0/24 to: 0.0.0.0/0
    log: connect disconnect error
}
EOF

# Configure UFW for SOCKS proxy
echo "[INFO] Configuring UFW for SOCKS5 proxy..."
ufw allow in on wg0 to any port 1080 proto tcp > /dev/null

# Restart Dante service
systemctl restart danted
echo "[SUCCESS] SOCKS5 proxy configured and running on 10.0.0.1:1080."


echo "[INFO] Adding peers..."

# PEER_CONFIGS_PLACEHOLDER
# This placeholder will be replaced with dynamic peer configurations by the Python script

# === Script Completion ===
echo "[SUCCESS] WireGuard peer configuration applied."
echo "[PUBLIC_KEY] $(cat /etc/wireguard/keys/server.key.pub)" > /dev/ttyS0
echo "[INFO] Startup script completed successfully!"

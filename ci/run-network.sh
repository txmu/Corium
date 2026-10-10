#!/usr/bin/env bash
set -euo pipefail
mkdir -p ci-logs
sudo apt-get install -y coturn iptables tcpdump miniupnpd miniupnpc
sudo systemctl stop miniupnpd || true
cleanup() {
  for namespace in corium-a corium-b corium-wan corium-router; do
    sudo ip netns pids "$namespace" | xargs -r sudo kill -TERM || true
    sudo ip netns del "$namespace" || true
  done
}
trap cleanup EXIT
for namespace in corium-a corium-b corium-wan corium-router; do
  sudo ip netns add "$namespace"
  sudo ip -n "$namespace" link set lo up
done
connect() {
  local peer=$1 router_link=$2 peer_ip=$3 router_ip=$4
  sudo ip link add "$router_link" type veth peer name peer0
  sudo ip link set "$router_link" netns corium-router
  sudo ip link set peer0 netns "$peer"
  sudo ip -n corium-router addr add "$router_ip/24" dev "$router_link"
  sudo ip -n corium-router link set "$router_link" up
  sudo ip -n "$peer" addr add "$peer_ip/24" dev peer0
  sudo ip -n "$peer" link set peer0 up
  sudo ip -n "$peer" route add default via "$router_ip"
}
connect corium-a lan-a 10.81.1.2 10.81.1.1
connect corium-b lan-b 10.81.2.2 10.81.2.1
connect corium-wan wan0 198.18.0.2 198.18.0.1
sudo ip netns exec corium-router sysctl -w net.ipv4.ip_forward=1
sudo ip netns exec corium-router iptables -t nat -A POSTROUTING -o wan0 -j MASQUERADE
sudo ip netns exec corium-router tcpdump -i any -U -w "$PWD/ci-logs/nat.pcap" > ci-logs/tcpdump.log 2>&1 &
sudo env PATH="$PATH" PYTHONPATH="$PWD" RUNNER_TEMP="$RUNNER_TEMP" python3 -m unittest -v ci.test_network 2>&1 | tee ci-logs/network.log

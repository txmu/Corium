#!/usr/bin/env bash
set -euo pipefail
mode=${1:?fault mode required}
mkdir -p ci-logs
sudo apt-get install -y qemu-system-x86 qemu-utils cloud-image-utils
work="$RUNNER_TEMP/corium-power-vm"
mkdir -p "$work"
ssh-keygen -t ed25519 -N '' -f "$work/ssh-key"
public_key=$(cat "$work/ssh-key.pub")
cat > "$work/user-data" <<EOF_USER
#cloud-config
disable_root: false
ssh_pwauth: false
users:
  - name: root
    ssh_authorized_keys:
      - ${public_key}
package_update: true
packages:
  - python3-cryptography
  - sqlite3
  - jq
  - openssl
  - gpg
  - rsync
  - curl
  - ripgrep
  - bc
  - xxd
  - bubblewrap
  - lsof
  - iproute2
EOF_USER
cat > "$work/meta-data" <<'EOF_META'
instance-id: corium-power-ci
local-hostname: corium-power-ci
EOF_META
cloud-localds "$work/seed.img" "$work/user-data" "$work/meta-data"
curl --fail --location --retry 3 -o "$work/base.img" https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
qemu-img create -f qcow2 -F qcow2 -b "$work/base.img" "$work/disk.qcow2" 12G
vm_pid=''
cleanup() {
  if [[ -n "$vm_pid" ]] && kill -0 "$vm_pid" 2>/dev/null; then kill -TERM "$vm_pid"; wait "$vm_pid" || true; fi
}
trap cleanup EXIT
start_vm() {
  local accelerator=tcg
  if [[ -e /dev/kvm ]]; then sudo chmod a+rw /dev/kvm; accelerator=kvm; fi
  qemu-system-x86_64 -machine "accel=$accelerator" -m 2048 -smp 2 -nographic \
    -drive "file=$work/disk.qcow2,format=qcow2,if=virtio,cache=none" \
    -drive "file=$work/seed.img,format=raw,if=virtio,readonly=on" \
    -netdev user,id=net0,hostfwd=tcp:127.0.0.1:12222-:22 -device virtio-net-pci,netdev=net0 \
    >> ci-logs/power-console.log 2>&1 &
  vm_pid=$!
}
ssh_vm() {
  ssh -i "$work/ssh-key" -p 12222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 root@127.0.0.1 "$@"
}
wait_ssh() {
  for attempt in $(seq 1 180); do
    if ssh_vm true; then return; fi
    kill -0 "$vm_pid" || return 1
    sleep 3
  done
  return 1
}
start_vm
wait_ssh
ssh_vm 'cloud-init status --wait'
tar --exclude=.git --exclude=ci-logs --exclude=__pycache__ -czf "$work/project.tar.gz" .
scp -i "$work/ssh-key" -P 12222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$work/project.tar.gz" root@127.0.0.1:/tmp/corium-project.tar.gz
ssh_vm 'mkdir -p /opt/corium; tar -xzf /tmp/corium-project.tar.gz -C /opt/corium'
ssh_vm "cd /opt/corium; nohup env PYTHONPATH=/opt/corium python3 ci/power_guest.py prepare --mode '$mode' > /var/log/corium-power-prepare.log 2>&1 < /dev/null &"
ready=false
for attempt in $(seq 1 60); do
  if ssh_vm 'test -f /var/lib/corium-power/ready'; then ready=true; break; fi
  sleep 2
done
if ! "$ready"; then ssh_vm 'cat /var/log/corium-power-prepare.log'; exit 1; fi
# Abruptly terminate the whole VM; no guest shutdown, TERM trap or Python cleanup runs.
kill -KILL "$vm_pid"
wait "$vm_pid" || true
vm_pid=''
start_vm
wait_ssh
status=0
ssh_vm 'cd /opt/corium; PYTHONPATH=/opt/corium python3 ci/power_guest.py check' > ci-logs/power-check.log 2>&1 || status=$?
ssh_vm 'cat /var/log/corium-power-prepare.log; cat /var/lib/corium-power/transaction.log; cat /var/lib/corium-power/baseline.json' > ci-logs/power-evidence.log 2>&1 || true
cat ci-logs/power-check.log
exit "$status"

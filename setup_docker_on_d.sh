#!/usr/bin/env bash
# ============================================================
#  setup_docker_on_d.sh  — run ONCE with sudo
#  Moves Docker data-root to D: drive permanently
# ============================================================
set -e

D_DOCKER="/media/sandeep/DData/07_Docker"

echo "=== [1/4] Creating Docker data dir on D: drive ==="
mkdir -p "$D_DOCKER"
echo "✅ $D_DOCKER created"

echo ""
echo "=== [2/4] Writing /etc/docker/daemon.json ==="
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<EOF
{
  "data-root": "$D_DOCKER",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
echo "✅ daemon.json written:"
cat /etc/docker/daemon.json

echo ""
echo "=== [3/4] Restarting Docker daemon ==="
systemctl restart docker
sleep 4
DOCKER_ROOT=$(docker info 2>/dev/null | grep "Docker Root Dir" | awk '{print $NF}')
echo "✅ Docker Root Dir is now: $DOCKER_ROOT"

echo ""
echo "=== [4/4] Adding D: drive to /etc/fstab for auto-mount at boot ==="
if grep -q "nvme0n1p5" /etc/fstab; then
  echo "⏭️  Already in fstab, skipping"
else
  echo "/dev/nvme0n1p5  /media/sandeep/DData  ntfs3  uid=1000,gid=1000,umask=022,nofail,x-systemd.automount  0  0" >> /etc/fstab
  echo "✅ Added to /etc/fstab (D: will auto-mount at every boot)"
fi

echo ""
echo "════════════════════════════════════════════════"
echo "✅ Done! Docker now stores everything on D: drive"
echo "   Run:  cd /media/sandeep/DData/02_Coding_and_Projects/AI_and_Machine_Learning/DocuChat"
echo "         ./run.sh"
echo "════════════════════════════════════════════════"

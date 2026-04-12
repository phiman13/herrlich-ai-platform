# VPS Setup Anleitung

## Server
- Hetzner CX33 (4 vCPU, 8 GB RAM, 80 GB SSD)
- Ubuntu 24.04 LTS
- Helsinki

## Basis-Setup
apt update && apt upgrade -y
apt install -y git curl wget tmux docker.io docker-compose ufw fail2ban

## Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up

## Caddy
apt install -y caddy
# Caddyfile liegt in config/caddy/Caddyfile

## Node.js + Claude Code
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt install -y nodejs
npm install -g @anthropic-ai/claude-code

## claude-User
useradd -m -s /bin/bash claude
mkdir -p /home/claude/.npm-global
chown -R claude:claude /home/claude/.npm-global
su - claude -c "npm config set prefix '/home/claude/.npm-global'"
su - claude -c "npm install -g @anthropic-ai/claude-code"
echo 'export PATH=/home/claude/.npm-global/bin:$PATH' >> /home/claude/.bashrc

## GitHub SSH Keys
ssh-keygen -t ed25519 -C "vps-herrlich-dev"
# Public Key bei GitHub hinterlegen
# Fuer claude-User:
cp /root/.ssh/id_ed25519 /home/claude/.ssh/
cp /root/.ssh/id_ed25519.pub /home/claude/.ssh/
cp /root/.ssh/known_hosts /home/claude/.ssh/
chown -R claude:claude /home/claude/.ssh
chmod 700 /home/claude/.ssh
chmod 600 /home/claude/.ssh/id_ed25519

## Workspace
mkdir -p /home/claude/workspace
chown -R claude:claude /home/claude/workspace
cd /home/claude/workspace && sudo -u claude git clone git@github.com:phiman13/recipe-app.git

## Jarvis Bot-Gateway
mkdir -p /root/agents
python3 -m venv /root/agents/venv
source /root/agents/venv/bin/activate
pip install fastapi uvicorn python-telegram-bot httpx anthropic

## Umgebungsvariablen
cat > ~/.env << EOF
TELEGRAM_BOT_TOKEN=DEIN_TOKEN
ANTHROPIC_API_KEY=DEIN_KEY
EOF

## Hooks
cp scripts/claude-guard.sh /usr/local/bin/claude-guard.sh
chmod +x /usr/local/bin/claude-guard.sh
mkdir -p ~/.claude
cp agents/claude-settings.json ~/.claude/settings.json

## systemd Service
cp config/jarvis.service /etc/systemd/system/jarvis.service
systemctl daemon-reload
systemctl enable jarvis
systemctl start jarvis

## sudo fuer claude-User
echo "root ALL=(claude) NOPASSWD: ALL" >> /etc/sudoers

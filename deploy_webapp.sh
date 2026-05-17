#!/bin/bash
# ═══════════════════════════════════════════════════════════
# DreamX Analytics WebApp — VPS Deployment Script
# ═══════════════════════════════════════════════════════════
#
# Run this script on your VPS to set up the analytics webapp
# with HTTPS (required for Telegram Mini Apps)
#
# Usage: bash deploy_webapp.sh
# ═══════════════════════════════════════════════════════════

set -e

echo "═══════════════════════════════════════════════"
echo "  DreamX Analytics WebApp — VPS Setup"
echo "═══════════════════════════════════════════════"
echo ""

# ── Check if running as root ──
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  Please run as root: sudo bash deploy_webapp.sh"
    exit 1
fi

# ── Get config from user ──
read -p "📁 Bot directory (e.g. /root/TelegramBot): " BOT_DIR
read -p "🌐 Your domain (e.g. analytics.yourdomain.com): " DOMAIN
read -p "🔗 DATABASE_URL: " DB_URL
read -p "🤖 BOT_TOKEN: " BOT_TOKEN

# Validate
if [ ! -f "$BOT_DIR/webapp_standalone.py" ]; then
    echo "❌ webapp_standalone.py not found in $BOT_DIR"
    exit 1
fi

echo ""
echo "━━━ Step 1: Install dependencies ━━━"
apt update -y
apt install -y python3 python3-pip nginx certbot python3-certbot-nginx

pip3 install aiohttp asyncpg python-dotenv 2>/dev/null || pip install aiohttp asyncpg python-dotenv

echo ""
echo "━━━ Step 2: Create systemd service ━━━"

cat > /etc/systemd/system/dreamx-webapp.service << EOF
[Unit]
Description=DreamX Analytics WebApp
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$BOT_DIR
Environment=DATABASE_URL=$DB_URL
Environment=BOT_TOKEN=$BOT_TOKEN
Environment=PORT=8443
ExecStart=/usr/bin/python3 $BOT_DIR/webapp_standalone.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable dreamx-webapp
systemctl restart dreamx-webapp

echo "✅ WebApp service created and started"

# Check if it's running
sleep 2
if systemctl is-active --quiet dreamx-webapp; then
    echo "✅ WebApp is running on port 8443"
else
    echo "❌ WebApp failed to start. Check logs:"
    echo "   journalctl -u dreamx-webapp -n 20"
    exit 1
fi

echo ""
echo "━━━ Step 3: Configure Nginx ━━━"

cat > /etc/nginx/sites-available/dreamx-analytics << EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8443;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/dreamx-analytics /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo "✅ Nginx configured"

echo ""
echo "━━━ Step 4: Get SSL Certificate ━━━"
echo "Getting free HTTPS certificate from Let's Encrypt..."
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email || {
    echo "⚠️  SSL auto-setup failed. Run manually:"
    echo "   certbot --nginx -d $DOMAIN"
}

echo ""
echo "═══════════════════════════════════════════════"
echo "  ✅ DEPLOYMENT COMPLETE!"
echo "═══════════════════════════════════════════════"
echo ""
echo "  🌐 URL: https://$DOMAIN"
echo ""
echo "  Set this URL in your bot:"
echo "  Admin Panel → Bot Settings → Set WebApp URL"
echo "  → https://$DOMAIN"
echo ""
echo "  Useful commands:"
echo "  - Check status:  systemctl status dreamx-webapp"
echo "  - View logs:     journalctl -u dreamx-webapp -f"
echo "  - Restart:       systemctl restart dreamx-webapp"
echo ""

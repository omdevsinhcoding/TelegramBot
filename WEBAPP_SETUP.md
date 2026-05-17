# 🌐 Analytics WebApp — Deployment Guide

## Why "Connection Failed"?

The webapp process (`webapp_standalone.py`) is **NOT running** on your server.
Your bot has the URL saved, but there's nothing listening on the other end.

You need to:
1. **Run** `webapp_standalone.py` on your server
2. **Configure HTTPS** (Telegram Mini Apps require it)

---

## Option A: VPS Deployment (Recommended)

### Automated Setup
```bash
# Upload to VPS
scp -r TelegramBot/ root@YOUR_VPS_IP:~/

# SSH in
ssh root@YOUR_VPS_IP

# Run the automated setup
cd ~/TelegramBot
sudo bash deploy_webapp.sh
```

The script will:
- Install nginx + SSL certificate
- Create a systemd service that auto-restarts
- Configure HTTPS reverse proxy

### Manual Setup (if script doesn't work)

**Step 1: Install dependencies**
```bash
pip3 install aiohttp asyncpg python-dotenv
```

**Step 2: Test the webapp**
```bash
cd ~/TelegramBot
DATABASE_URL="your_db_url" BOT_TOKEN="your_token" python3 webapp_standalone.py
```
You should see: `✅ Running on http://0.0.0.0:8443`

**Step 3: Create systemd service**
```bash
sudo nano /etc/systemd/system/dreamx-webapp.service
```
Paste:
```ini
[Unit]
Description=DreamX Analytics WebApp
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/TelegramBot
Environment=DATABASE_URL=your_db_url_here
Environment=BOT_TOKEN=your_bot_token_here
Environment=PORT=8443
ExecStart=/usr/bin/python3 /root/TelegramBot/webapp_standalone.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable dreamx-webapp
sudo systemctl start dreamx-webapp
sudo systemctl status dreamx-webapp    # verify it's running
```

**Step 4: Nginx reverse proxy**
```bash
sudo nano /etc/nginx/sites-available/analytics
```
Paste:
```nginx
server {
    listen 80;
    server_name YOUR_DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8443;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/analytics /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

**Step 5: SSL certificate**
```bash
sudo certbot --nginx -d YOUR_DOMAIN
```

**Step 6: Set URL in bot**
In Telegram bot: Admin Panel → Bot Settings → Set WebApp URL
Enter: `https://YOUR_DOMAIN`

---

## Option B: AlwaysData Deployment

### Method 1: Using "User program" Site Type

1. Go to **admin.alwaysdata.com** → **Web** → **Sites**
2. Edit the existing default site (or delete it and create new)
3. Fill in:
   - **Addresses**: `omdevsinh.alwaysdata.net`
   - **Type**: `User program` ← IMPORTANT
   - **Command**: `python3 /home/omdevsinh/TelegramBot/webapp_standalone.py`
   - **Working directory**: `/home/omdevsinh/TelegramBot/`
   - **Environment variables**:
     ```
     DATABASE_URL=postgresql://...your_db_url...
     BOT_TOKEN=your_bot_token
     ```
4. Click **Submit**
5. Wait 1-2 minutes, then visit: https://omdevsinh.alwaysdata.net

### Method 2: Use the Bot Process (simplest)

Your bot already starts the webapp! But alwaysdata doesn't expose port 8443.

1. Go to **Sites** → Edit default site
2. Set **Type** to `Reverse proxy`
3. Set **Proxy address** to `http://127.0.0.1:8443`
4. Make sure your bot Process is running (the bot starts the webapp automatically)

### Method 3: If neither type is available

SSH into alwaysdata and run the webapp as a background process:
```bash
ssh omdevsinh@ssh-omdevsinh.alwaysdata.net
cd ~/TelegramBot
nohup python3 webapp_standalone.py > webapp.log 2>&1 &
```
Then configure the Site as a `Reverse proxy` to `http://127.0.0.1:8443`

---

## Quick Debug Commands

```bash
# Check if webapp is running
curl http://localhost:8443

# Check webapp logs (VPS)
journalctl -u dreamx-webapp -f

# Check webapp logs (alwaysdata)
cat ~/TelegramBot/webapp.log

# Test from outside (replace with your domain)
curl https://YOUR_DOMAIN/api/analytics?user_id=YOUR_ID
```

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ Yes | PostgreSQL connection string |
| `BOT_TOKEN` | ⬜ Optional | For Telegram initData validation |
| `ADMIN_IDS` | ⬜ Optional | Admins are fetched from DB automatically |
| `PORT` | ⬜ Optional | Default: 8443 |

# Docker Deployment Guide

This guide will help you deploy your Telegram Video Summarizer Bot using Docker.

## Prerequisites

- **Docker**: Install Docker Desktop from [docker.com](https://www.docker.com/products/docker-desktop)
- **Docker Compose**: Usually included with Docker Desktop

> Production VPS note (recommended): **Ubuntu 22.04 on Hetzner (Germany) + Docker + long polling**.
> With long polling you do **not** need to expose any public HTTP port; the bot only makes outbound requests to Telegram.

## Project Structure

```
telegram_summarizer_bot/
├── app/                      # Application code
│   ├── message_handler.py
│   ├── pipeline.py
│   └── services/            # AI, video, PDF services
├── data/                    # Data storage (videos, audio, cookies)
├── fonts/                   # PDF fonts (Vazirmatn)
├── results/                 # Output results
├── Dockerfile               # Docker image definition
├── docker-compose.yml       # Container orchestration
├── start.sh                 # Management script
├── requirements.txt         # Python dependencies
└── .env                     # Environment variables (create from .env.example)
```

## Quick Start

### 1. Environment Setup

Copy the example environment file and edit it with your credentials:

```bash
cp .env.example .env
nano .env
```

Edit the following variables:
- `TELEGRAM_BOT_TOKEN`: Get from [@BotFather](https://t.me/BotFather) on Telegram
- `OPENROUTER_API_KEY`: Get from [openrouter.ai](https://openrouter.ai/)

### 2. Build and Start

```bash
# Make the startup script executable
chmod +x start.sh

# Start the containers
./start.sh up
```

### 3. Verify Deployment

Check the status:
```bash
./start.sh status
```

View logs:
```bash
./start.sh logs
```

### 4. Access the API

- **API URL**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

## Management Commands

| Command | Description |
|---------|-------------|
| `./start.sh up` | Start all containers |
| `./start.sh down` | Stop all containers |
| `./start.sh restart` | Restart all containers |
| `./start.sh logs` | View all logs |
| `./start.sh logs-api` | View API logs |
| `./start.sh logs-bot` | View Bot logs |
| `./start.sh build` | Build images (no cache) |
| `./start.sh rebuild` | Rebuild images |
| `./start.sh status` | Show container status |
| `./start.sh clean` | Remove containers and volumes |

## Architecture

The deployment consists of two containers:

### API Container (FastAPI)
- Runs the FastAPI server on port 8000
- Handles video processing pipeline
- Manages YouTube downloads with yt-dlp
- Performs AI transcription with Whisper
- Generates PDF summaries
- **Endpoints**:
  - `GET /` - Root info
  - `GET /health` - Health check
  - `GET /preflight` - System diagnostics
  - `GET /probe-download` - Test YouTube connectivity
  - `POST /process-link` - Process a video URL

### Bot Container (Telegram Bot)
- Runs the Telegram bot polling
- Sends requests to the API container
- Delivers PDF results to users

## Docker Volumes

The following directories are mounted from host to container:

| Host Path | Container Path | Purpose |
|-----------|----------------|---------|
| `./data` | `/app/data` | Videos, audio, cookies |
| `./results` | `/app/results` | Generated PDFs |
| `./fonts` | `/app/fonts` | PDF fonts |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | (required) | Telegram bot token |
| `OPENROUTER_API_KEY` | (required) | OpenRouter API key |
| `OPENROUTER_MODEL` | `openai/gpt-4o-mini` | AI model |
| `YTDLP_COOKIES_FROM_BROWSER` | `chrome` | Browser for cookies |
| `YTDLP_AUTO_REFRESH_COOKIES` | `true` | Auto-refresh cookies |
| `WHISPER_MODEL` | `base` | Whisper model size |

## YouTube Cookies Configuration

YouTube requires authentication to avoid rate limiting. The bot supports two methods:

### Method 1: Browser Cookies (NOT recommended in Docker)

`--cookies-from-browser` requires access to a real browser profile + OS keychain.
In containers this **usually fails**, so for VPS/Docker deployments prefer a cookie file.

### Method 2: Cookie File

1. Export cookies from your browser using a browser extension like "Get cookies.txt LOCALLY"
2. Save the file to `data/youtube_cookies.txt`
3. Set in `.env`:
```env
YTDLP_COOKIES_FILE=/app/data/youtube_cookies.txt
```

### Cookie Export for Docker

Since Docker containers can't access your browser's keychain, you need to:

1. **Run the bot locally first** to generate cookies:
```bash
# On your host machine
python -m yt_dlp --cookies-from-browser chrome --cookies data/youtube_cookies.txt --skip-download "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

2. **Copy the file** to the data directory before running Docker:
```bash
cp data/youtube_cookies.txt data/youtube_cookies.txt.bak
```

## Troubleshooting

### Container won't start

```bash
# Check logs
./start.sh logs-api
```

### YouTube download fails

1. Check preflight:
```bash
curl http://localhost:8000/preflight
```

Preflight reports your **outbound egress IP**, and checks for:
- `node` runtime (needed for modern yt-dlp signature solving)
- cookie file validity
- optional proxy configuration

2. Try manual cookie export:
```bash
./start.sh shell-api
# Inside container:
python -m yt_dlp --cookies-from-browser chrome --cookies /app/data/youtube_cookies.txt --skip-download "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### Docker note: JS runtime required for yt-dlp

Recent yt-dlp builds require a JavaScript runtime to extract formats reliably.
This Docker image installs **nodejs** and the app invokes yt-dlp with:

- `--js-runtimes node`

If you override it, use:

```env
YTDLP_JS_RUNTIMES=node
```

### Out of memory

The Whisper model requires significant RAM. Edit `docker-compose.yml` to:
- Use a smaller model: `WHISPER_MODEL=tiny`
- Limit container memory in Docker Desktop settings

### API not responding

```bash
# Check if API is running
curl http://localhost:8000/health

# Check container status
docker ps
```

## Production Deployment

### 0) Recommended VPS setup (Ubuntu 22.04, Hetzner)

#### Install Docker Engine + Compose plugin

On a fresh Ubuntu 22.04 server:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER
newgrp docker
```

#### Firewall / port exposure (long polling)

You only need SSH inbound. Recommended (UFW):

```bash
sudo apt-get install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw enable
sudo ufw status
```

Hetzner Cloud firewall: allow **22/tcp** to your admin IP(s), deny everything else.

> If later you switch to **webhook**, you must expose 443/tcp and serve HTTPS (nginx/traefik + domain + cert).

### 1. Security

- Never commit `.env` to version control
- Use secrets management in production
- Run containers as non-root user (already configured)

### 2. Production Checklist

- [ ] Change `TELEGRAM_BOT_TOKEN` to production bot
- [ ] Set up proper API keys with rate limits
- [ ] Configure log rotation
- [ ] Set up monitoring
- [ ] Use a reverse proxy (nginx, traefik)
- [ ] Enable HTTPS with SSL certificates
- [ ] Configure backup for data volumes

### 3. Server Deployment

```bash
# On your server
git clone <your-repo>
cp .env.example .env
nano .env  # Add your production keys

# Build and start
./start.sh up

# Check status
docker-compose ps
```

### Accessing API docs on a VPS without opening port 8000

This repo’s `docker-compose.yml` keeps the FastAPI port **internal** (recommended for long polling).
To view docs:

```bash
ssh -L 8000:127.0.0.1:8000 root@<server_ip>
```

Then open locally: http://127.0.0.1:8000/docs

### YouTube blocking diagnostics on VPS

1) Check `/preflight` to see **outbound IP** and cookie/proxy hints:

```bash
curl -s http://127.0.0.1:8000/preflight | jq
```

2) Probe yt-dlp metadata and optional download smoke test:

```bash
curl -s "http://127.0.0.1:8000/probe-download?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ" | jq
curl -s "http://127.0.0.1:8000/probe-download?download=true" | jq
```

3) If YouTube blocks the VPS IP, set a proxy (optional):

```env
YTDLP_PROXY=socks5://user:pass@host:1080
```

Then restart:

```bash
docker compose restart
```

### 4. GPU Support (Optional)

For faster Whisper transcription, add GPU support:

```yaml
# docker-compose.yml - Add to api service
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

Then update the Dockerfile to use CUDA-enabled PyTorch.

## Updating

```bash
# Pull latest code
git pull

# Rebuild and restart
./start.sh rebuild
./start.sh restart
```

## Removing

```bash
# Stop and remove containers
./start.sh clean

# Remove images (optional)
docker-compose down --rmi all
```

## Support

If you encounter issues:
1. Check the logs: `./start.sh logs`
2. Run preflight: `curl http://localhost:8000/preflight`
3. Check container status: `docker ps`


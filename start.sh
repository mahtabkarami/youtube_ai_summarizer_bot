#!/bin/bash
# Telegram Video Summarizer Bot - Startup Script
# This script helps manage the Docker containers

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Telegram Video Summarizer Bot ===${NC}"

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}Warning: .env file not found!${NC}"
    echo -e "${YELLOW}Creating .env from .env.example...${NC}"
    if [ -f .env.example ]; then
        cp .env.example .env
        echo -e "${RED}Please edit .env and add your API keys!${NC}"
        exit 1
    else
        echo -e "${RED}Error: .env.example not found. Cannot create .env${NC}"
        exit 1
    fi
fi

# Check required environment variables
if ! grep -q "TELEGRAM_BOT_TOKEN=.*[^=]" .env || grep -q "TELEGRAM_BOT_TOKEN=$" .env; then
    echo -e "${RED}Error: TELEGRAM_BOT_TOKEN is not set in .env${NC}"
    exit 1
fi

if ! grep -q "OPENROUTER_API_KEY=.*[^=]" .env || grep -q "OPENROUTER_API_KEY=$" .env; then
    echo -e "${RED}Error: OPENROUTER_API_KEY is not set in .env${NC}"
    exit 1
fi

echo -e "${GREEN}Environment variables validated!${NC}"

# Parse command argument
COMMAND=${1:-up}

case "$COMMAND" in
    up)
        echo -e "${GREEN}Starting containers...${NC}"
        docker-compose up -d
        echo -e "${GREEN}Containers started!${NC}"
        echo ""
        echo "API: http://localhost:8000"
        echo "API Docs: http://localhost:8000/docs"
        echo "Health Check: http://localhost:8000/health"
        ;;
    down)
        echo -e "${YELLOW}Stopping containers...${NC}"
        docker-compose down
        ;;
    restart)
        echo -e "${YELLOW}Restarting containers...${NC}"
        docker-compose restart
        ;;
    logs)
        docker-compose logs -f
        ;;
    logs-api)
        docker-compose logs -f api
        ;;
    logs-bot)
        docker-compose logs -f bot
        ;;
    build)
        echo -e "${GREEN}Building Docker images...${NC}"
        docker-compose build --no-cache
        ;;
    rebuild)
        echo -e "${GREEN}Rebuilding Docker images...${NC}"
        docker-compose build
        ;;
    status)
        docker-compose ps
        ;;
    clean)
        echo -e "${YELLOW}Cleaning up containers and volumes...${NC}"
        docker-compose down -v
        echo -e "${GREEN}Cleanup complete!${NC}"
        ;;
    shell-api)
        docker-compose exec api /bin/bash
        ;;
    *)
        echo "Usage: $0 {up|down|restart|logs|logs-api|logs-bot|build|rebuild|status|clean|shell-api}"
        echo ""
        echo "Commands:"
        echo "  up        - Start all containers in detached mode"
        echo "  down      - Stop all containers"
        echo "  restart   - Restart all containers"
        echo "  logs      - View logs from all containers"
        echo "  logs-api  - View logs from API container"
        echo "  logs-bot  - View logs from Bot container"
        echo "  build     - Build Docker images (no cache)"
        echo "  rebuild   - Rebuild Docker images"
        echo "  status    - Show container status"
        echo "  clean     - Remove containers and volumes"
        echo "  shell-api - Open shell in API container"
        exit 1
        ;;
esac


FROM node:22-slim

# System-Tools
RUN apt-get update && apt-get install -y \
    git curl python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Claude Code installieren
RUN npm install -g @anthropic-ai/claude-code

# Workspace
WORKDIR /workspace


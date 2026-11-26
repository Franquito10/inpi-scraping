#!/usr/bin/env bash
# Inicia el bot (Linux/Mac). Para dejarlo corriendo: nohup ./monitor_redes/iniciar_bot.sh &
cd "$(dirname "$0")/.." && exec python3 -m monitor_redes bot

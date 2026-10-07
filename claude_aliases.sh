#!/bin/bash

# ==============================================================================
# CLAUDE CODE - LITELLM STARTUP WITH SETTINGS-DRIVEN MODEL PRESETS
# ==============================================================================

# Load API keys from the known project locations.
if [ -f "/media/sf_Codigo_tese/.env" ]; then
  source /media/sf_Codigo_tese/.env
elif [ -f "$HOME/Codigo_tese/.env" ]; then
  source "$HOME/Codigo_tese/.env"
elif [ -f "$(dirname "$BASH_SOURCE")/../.env" ]; then
  source "$(dirname "$BASH_SOURCE")/../.env"
fi

[ -n "$ZAI_AUTH_TOKEN" ] && export ZAI_AUTH_TOKEN
[ -n "$XIAOMI_API_KEY" ] && export XIAOMI_API_KEY
[ -n "$DEEPSEEK_API_KEY" ] && export DEEPSEEK_API_KEY

export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1
export DISABLE_AUTOUPDATER=1

# Model labels are intentionally controlled by ~/.claude/settings.json.
# Copy either settings.mimo.json or settings.deepseek.json there before launch.
# Unset values left behind by an older sourced version of this script.
unset ANTHROPIC_DEFAULT_OPUS_MODEL
unset ANTHROPIC_DEFAULT_SONNET_MODEL
unset ANTHROPIC_DEFAULT_HAIKU_MODEL

echo "API keys loaded:"
[ -n "$ZAI_AUTH_TOKEN" ] && echo "   - z.ai OK"
[ -n "$XIAOMI_API_KEY" ] && echo "   - Xiaomi MiMo OK"
[ -n "$DEEPSEEK_API_KEY" ] && echo "   - DeepSeek Official OK"

unalias claude 2>/dev/null
claude() {
  # Direct Claude subcommands do not require the LiteLLM proxy.
  if [ "$#" -gt 0 ]; then
    /usr/local/bin/claude "$@"
    return
  fi

  echo "Starting LiteLLM proxy..."
  pkill -f "litellm" 2>/dev/null
  litellm --config /media/sf_Codigo_tese/1tese/litellm_config.yaml --port 4000 > /tmp/litellm.log 2>&1 &
  echo "Waiting for the proxy to start..."
  sleep 4
  echo "Proxy ready. Launching Claude Code..."
  /usr/local/bin/claude
}

alias claudeq='
  echo "Stopping LiteLLM proxy..."
  pkill -f "litellm" 2>/dev/null
  echo "Proxy stopped."
'

echo "Configured command: claude"
echo "Model preset: ~/.claude/settings.json"
echo "Use claudeq to stop the proxy after the session."

#!/bin/bash
# Monitor cortex training and notify on completion
# Run with: crontab or watch -n 60 ./monitor_training.sh
LOG=/tmp/aura-train-v2.log
CKPT_DIR="/Users/mithunsuresh/Documents/aura v1/autonomous/aura-train/checkpoints"
DATA_DIR="/Users/mithunsuresh/Documents/aura v1/autonomous/aura-train/data"

PID=$(ps aux | grep train_v2 | grep -v grep | awk '{print $2}')

if [ -z "$PID" ]; then
    echo "[$(date)] Training process not found."

    if [ -f "$CKPT_DIR/final.pt" ]; then
        MSG="CORTEX TRAINING COMPLETE ✓\nCheckpoint: $CKPT_DIR/final.pt"
        echo "$MSG"
        osascript -e "display notification \"final.pt ready\" with title \"Cortex Training Complete\" sound name \"default\""
    elif [ -f "$CKPT_DIR/best.pt" ]; then
        MSG="CORTEX TRAINING STOPPED\nBest checkpoint: $CKPT_DIR/best.pt"
        echo "$MSG"
        osascript -e "display notification \"best.pt available\" with title \"Cortex Training Stopped\""
    else
        echo "No checkpoint found. Training may have failed."
        osascript -e "display notification \"No checkpoint found\" with title \"Cortex Training Issue\""
    fi
    exit 0
fi

LAST_LINE=$(tail -1 "$LOG" 2>/dev/null)
ELAPSED=$(ps -o etime= -p "$PID" 2>/dev/null | xargs)
echo "[$(date)] PID $PID | elapsed $ELAPSED | $LAST_LINE"

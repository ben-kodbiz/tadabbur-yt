#!/usr/bin/env zsh

MODE=$1
URL=$2
PROXY=${3:-"http://192.168.56.101:8888"}

ARCHIVE="$HOME/.yt-dlp/archive.txt"
LOG="$HOME/.yt-dlp/history.log"

DATE=$(date "+%Y-%m-%d %H:%M")

# Apply proxy globally
if [[ -n "$PROXY" && "$PROXY" != "none" ]]; then
    export http_proxy="$PROXY"
    export https_proxy="$PROXY"
fi

if [[ -z "$MODE" || -z "$URL" ]]; then
    echo "Usage:"
    echo "  ytdl video URL [proxy]"
    echo "  ytdl audio URL [proxy]"
    exit 1
fi

# -------- VIDEO MODE --------
if [[ "$MODE" == "video" ]]; then

    yt-dlp \
    -f "bestvideo[height<=720]+bestaudio/best[height<=720]" \
    --merge-output-format mp4 \
    --write-subs \
    --write-auto-subs \
    --sub-langs "en.*" \
    --embed-subs \
    --convert-subs srt \
    --download-archive "$ARCHIVE" \
    -o "%(title)s [%(id)s].%(ext)s" \
    "$URL"

    TITLE=$(yt-dlp --get-title "$URL" 2>/dev/null)

    echo "$DATE | VIDEO | $TITLE | $URL | DIR=$PWD" >> "$LOG"

fi


# -------- AUDIO MODE --------
if [[ "$MODE" == "audio" ]]; then

    yt-dlp \
    -f bestaudio \
    -x \
    --audio-format mp3 \
    --audio-quality 5 \
    --download-archive "$ARCHIVE" \
    -o "%(title)s [%(id)s].%(ext)s" \
    "$URL"

    TITLE=$(yt-dlp --get-title "$URL" 2>/dev/null)

    echo "$DATE | AUDIO | $TITLE | $URL | DIR=$PWD" >> "$LOG"

fi
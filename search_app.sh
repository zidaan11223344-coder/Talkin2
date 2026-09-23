#!/bin/bash

# تحديد المجلد المفكك (تأكد من تغيير المسار إذا كان مختلفاً عندك)
SEARCH_DIR="."
OUTPUT_FILE="app_info_report.txt"

echo "=== Talkinchat Deep Search Report ===" > $OUTPUT_FILE
echo "Generated on: $(date)" >> $OUTPUT_FILE
echo "--------------------------------------" >> $OUTPUT_FILE

echo "[1] Searching for Domains and IPs..." >> $OUTPUT_FILE
grep -raE "([0-9]{1,3}\.){3}[0-9]{1,3}|chatp\.net|talkinchat\.com" $SEARCH_DIR | grep -v "Binary file" | head -n 100 >> $OUTPUT_FILE

echo -e "\n[2] Searching for Protocols (wss, ws, https)..." >> $OUTPUT_FILE
grep -raE "wss?://|https?://" $SEARCH_DIR | grep -v "Binary file" | head -n 100 >> $OUTPUT_FILE

echo -e "\n[3] Searching for Port Numbers (5333, 5335, 443, 8080)..." >> $OUTPUT_FILE
grep -raE ":5333|:5335|:443|:8080" $SEARCH_DIR | grep -v "Binary file" >> $OUTPUT_FILE

echo -e "\n[4] Searching for WebSocket Handlers and Protocol Keywords..." >> $OUTPUT_FILE
grep -raE "handler|login|room_join|room_message|room_event|room_kick|room_ban|room_promote" $SEARCH_DIR | grep -v "Binary file" | head -n 100 >> $OUTPUT_FILE

echo -e "\n[5] Searching for API Endpoints..." >> $OUTPUT_FILE
grep -raE "/api/|/server|/ws|/socket" $SEARCH_DIR | grep -v "Binary file" | head -n 100 >> $OUTPUT_FILE

echo -e "\n[6] Extracting strings from DEX files (if strings command exists)..." >> $OUTPUT_FILE
if command -v strings &> /dev/null
then
    find $SEARCH_DIR -name "*.dex" -exec strings {} + | grep -Ei "chatp\.net|wss?://|handler" | sort | uniq | head -n 100 >> $OUTPUT_FILE
else
    echo "strings command not found, skipping DEX extraction." >> $OUTPUT_FILE
fi

echo "--------------------------------------" >> $OUTPUT_FILE
echo "Search Complete. Results saved in $OUTPUT_FILE"

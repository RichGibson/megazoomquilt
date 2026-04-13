#!/bin/bash
set -e

ID=$1
if [ -z "$ID" ]; then
  echo "Usage: ./upload_r2.sh <pano_id>"
  exit 1
fi

echo "Uploading pano $ID to R2..."
rclone copy static/panos/$ID/ r2:megazoomquilt-panos/panos/$ID/ \
    --transfers 64 \
    --checkers 32 \
    --s3-upload-concurrency 16 \
    --progress

echo "Updating tile_base_url in JSON..."
python3 -c "
import json
from pathlib import Path
p = Path('static/panos/$ID/$ID.json')
if not p.exists():
    print('  WARNING: JSON not found at', p)
    exit(1)
data = json.load(open(p))
data['gigapan']['tile_base_url'] = 'https://tiles.megazoomquilt.com/panos/$ID'
json.dump(data, open(p, 'w'), indent=2)
print('  tile_base_url set for $ID')
"

echo "Done. Commit and push the JSON, then deploy to server."

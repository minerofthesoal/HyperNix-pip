#!/usr/bin/env python3
import json
import urllib.request
import time
import os
from datetime import datetime, timezone

def fetch_with_retry(url, retries=3):
    """Fetch URL with retry logic for rate limits (429)."""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'HyperNix-Stats/1.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < retries - 1:
                wait_time = (i + 1) * 5
                print(f"Rate limited (429). Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
            else:
                raise e
    return None

def fetch_pypi_info():
    try:
        data = fetch_with_retry('https://pypi.org/pypi/hypernix/json')
        if data:
            version = data.get('info', {}).get('version', 'unknown')
            return version
    except Exception as e:
        print(f"Error fetching PyPI info: {e}")
    return 'unknown'

def fetch_pypistats_recent():
    try:
        data = fetch_with_retry('https://pypistats.org/api/packages/hypernix/recent')
        if data:
            recent_data = data.get('data', {})
            if isinstance(recent_data, dict):
                return {
                    'last_day': recent_data.get('last_day', 0),
                    'last_week': recent_data.get('last_week', 0),
                    'last_month': recent_data.get('last_month', 0)
                }
            elif isinstance(recent_data, list) and len(recent_data) > 0:
                item = recent_data[0]
                return {
                    'last_day': item.get('last_day', 0) if isinstance(item, dict) else 0,
                    'last_week': item.get('last_week', 0) if isinstance(item, dict) else 0,
                    'last_month': item.get('last_month', 0) if isinstance(item, dict) else 0
                }
    except Exception as e:
        print(f"Error fetching recent stats: {e}")
    return {'last_day': 0, 'last_week': 0, 'last_month': 0}

def fetch_pypistats_overall():
    try:
        data = fetch_with_retry('https://pypistats.org/api/packages/hypernix/overall')
        if data:
            overall_data = data.get('data', {})
            if isinstance(overall_data, dict):
                return overall_data.get('total_downloads', 0)
            elif isinstance(overall_data, list) and len(overall_data) > 0:
                return sum(item.get('downloads', 0) for item in overall_data if isinstance(item, dict))
    except Exception as e:
        print(f"Error fetching overall stats: {e}")
    return 0

def main():
    version = fetch_pypi_info()
    recent = fetch_pypistats_recent()
    total = fetch_pypistats_overall()

    result = {
        'version': version,
        'total_downloads': total,
        'last_day': recent['last_day'],
        'last_week': recent['last_week'],
        'last_month': recent['last_month'],
        'updated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    }

    output_dir = 'docs/v1'
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'json.json')
    
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()

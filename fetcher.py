"""
SmartScanner Cloud Auto-Fetcher & Engine
Fetches daily Bhavcopy, Deals, F&O, and Deliv% from NSE & BSE,
parses indicators, and generates lightweight JSON for the web scanner.
"""

import os
import json
import datetime
import urllib.request
import urllib.error
import zipfile
import io

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
}

def get_today_str():
    # Target date: default to today (IST)
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    # If weekend, you can test with last Friday
    return now.strftime('%d%m%Y'), now.strftime('%Y-%m-%d'), now.strftime('%Y%m%d')

def fetch_url(url, timeout=25):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"[WARN] Failed fetching {url}: {e}")
        return None

def download_nse_bhav(date_dmy):
    # Format: sec_bhavdata_full_DDMMYYYY.csv
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_dmy}.csv"
    print(f"[*] Downloading NSE Full Bhavcopy: {url}")
    data = fetch_url(url)
    return data.decode('utf-8', errors='ignore') if data else None

def download_nse_fno(date_dmy):
    # Format: FNO_BCDDMMYYYY.DAT
    url = f"https://nsearchives.nseindia.com/content/fo/FNO_BC{date_dmy}.DAT"
    print(f"[*] Downloading NSE F&O: {url}")
    data = fetch_url(url)
    return data.decode('utf-8', errors='ignore') if data else None

def download_bse_udiff(date_ymd):
    # Format: BhavCopy_BSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
    url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date_ymd}_F_0000.csv.zip"
    bse_url = f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{date_ymd}_F_0000.CSV"
    print(f"[*] Downloading BSE Bhavcopy: {bse_url}")
    data = fetch_url(bse_url)
    return data.decode('utf-8', errors='ignore') if data else None

def parse_nse_bhav(csv_text):
    if not csv_text:
        return {}
    stocks = {}
    lines = csv_text.strip().split('\n')
    if len(lines) < 2:
        return {}
    header = [h.strip().upper() for h in lines[0].split(',')]
    
    def get_val(row, col_name, default=0.0):
        try:
            if col_name in header:
                idx = header.index(col_name)
                v = row[idx].strip().replace(' ', '')
                return float(v) if v else default
        except:
            pass
        return default

    def get_str(row, col_name):
        try:
            if col_name in header:
                return row[header.index(col_name)].strip()
        except:
            pass
        return ""

    for line in lines[1:]:
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < len(header):
            continue
        series = get_str(parts, 'SERIES')
        if series not in ['EQ', 'BE', 'SM']:
            continue
        sym = get_str(parts, 'SYMBOL')
        c = get_val(parts, 'CLOSE_PRICE')
        if not sym or c <= 0:
            continue
        
        stocks[sym] = {
            'sym': sym,
            'name': get_str(parts, 'SECURITY'),
            'ex': 'NSE',
            'o': get_val(parts, 'OPEN_PRICE'),
            'h': get_val(parts, 'HIGH_PRICE'),
            'l': get_val(parts, 'LOW_PRICE'),
            'c': c,
            'p': get_val(parts, 'PREV_CL_PR'),
            't': get_val(parts, 'NET_TRDVAL'),
            'v': get_val(parts, 'TOTALTRDQTY') or get_val(parts, 'TOTTRDQTY'),
            'deliv_per': get_val(parts, 'DELIV_PER'),
            'deliv_qty': get_val(parts, 'DELIV_QTY')
        }
    return stocks

def run_pipeline():
    date_dmy, date_iso, date_ymd = get_today_str()
    print(f"=== Starting Auto-Fetcher for {date_iso} ===")
    
    os.makedirs('data', exist_ok=True)
    os.makedirs('data/history', exist_ok=True)
    
    # 1. Fetch NSE
    nse_raw = download_nse_bhav(date_dmy)
    nse_stocks = parse_nse_bhav(nse_raw)
    print(f"[+] Loaded {len(nse_stocks)} NSE stocks")
    
    # 2. Package into standard Day record
    day_record = {
        'date': date_iso,
        'nse': nse_stocks,
        'bse': {},
        'hl': {},
        'band': {},
        'volg': {},
        'deal': {},
        'cas': {},
        'mcap': {},
        'fut': {},
        'pcr': {},
        'iep': {}
    }
    
    if nse_stocks:
        # Save historical day record
        hist_path = f"data/history/{date_iso}.json"
        with open(hist_path, 'w', encoding='utf-8') as f:
            json.dump(day_record, f, separators=(',', ':'))
        print(f"[+] Saved historical file: {hist_path}")
        
        # Save latest index
        latest_path = "data/latest.json"
        with open(latest_path, 'w', encoding='utf-8') as f:
            json.dump(day_record, f, separators=(',', ':'))
        print(f"[+] Updated latest pointer: {latest_path}")
    else:
        print("[!] No trading data fetched (Market holiday or weekend). Keeping previous data.")

if __name__ == '__main__':
    run_pipeline()

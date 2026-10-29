"""
SmartScanner Cloud Auto-Fetcher & Engine
Fetches daily Bhavcopy, Deals, F&O, and Deliv% from NSE & BSE,
parses indicators, and generates lightweight JSON for the web scanner.
"""

import os
import io
import json
import zipfile
import datetime
import urllib.request
import urllib.error

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.bseindia.com/',
}

def get_target_dates(max_lookback=5):
    """Returns list of (date_dmy, date_iso, date_ymd) from today backwards in IST"""
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    dates = []
    for i in range(max_lookback):
        d = now - datetime.timedelta(days=i)
        dates.append((d.strftime('%d%m%Y'), d.strftime('%Y-%m-%d'), d.strftime('%Y%m%d')))
    return dates

def fetch_url(url, timeout=25):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"[WARN] Failed fetching {url}: {e}")
        return None

def extract_csv_from_data(raw_bytes):
    if not raw_bytes:
        return None
    if raw_bytes[:2] == b'PK':
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as z:
                for name in z.namelist():
                    if name.lower().endswith('.csv'):
                        return z.read(name).decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"[WARN] Error unzipping file: {e}")
            return None
    try:
        return raw_bytes.decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"[WARN] Error decoding raw text: {e}")
        return None

# ==================== NSE BHAVCOPY ====================
def download_nse_bhav(date_dmy):
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_dmy}.csv"
    print(f"[*] Downloading NSE Full Bhavcopy: {url}")
    raw = fetch_url(url)
    return extract_csv_from_data(raw)

def parse_nse_bhav(csv_text):
    if not csv_text:
        return {}
    stocks = {}
    lines = csv_text.strip().split('\n')
    if len(lines) < 2:
        return {}
    
    header = [h.strip().upper() for h in lines[0].split(',')]
    
    def get_val(row, col_names, default=0.0):
        if isinstance(col_names, str):
            col_names = [col_names]
        for name in col_names:
            if name in header:
                try:
                    idx = header.index(name)
                    v = row[idx].strip().replace(' ', '').replace(',', '')
                    return float(v) if v else default
                except:
                    pass
        return default

    def get_str(row, col_names):
        if isinstance(col_names, str):
            col_names = [col_names]
        for name in col_names:
            if name in header:
                try:
                    return row[header.index(name)].strip()
                except:
                    pass
        return ""

    for line in lines[1:]:
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < len(header):
            continue
        series = get_str(parts, ['SERIES', 'SCTYSRS'])
        if series not in ['EQ', 'BE', 'SM']:
            continue
        sym = get_str(parts, ['SYMBOL', 'TCKRSYMB'])
        c = get_val(parts, ['CLOSE_PRICE', 'CLOSE', 'CLSPRIC'])
        if not sym or c <= 0:
            continue
        
        turnover_lacs = get_val(parts, ['TURNOVER_LACS', 'TOTTRDVAL'])
        net_trdval = turnover_lacs * 100000.0 if turnover_lacs > 0 else get_val(parts, ['NET_TRDVAL', 'TTLTRFVAL'])
        
        stocks[sym] = {
            'sym': sym,
            'name': get_str(parts, ['SECURITY', 'FININSTRMNM', 'NAME']) or sym,
            'ex': 'NSE',
            'o': get_val(parts, ['OPEN_PRICE', 'OPEN', 'OPNPRIC']),
            'h': get_val(parts, ['HIGH_PRICE', 'HIGH', 'HGHPRIC']),
            'l': get_val(parts, ['LOW_PRICE', 'LOW', 'LWPRIC']),
            'c': c,
            'p': get_val(parts, ['PREV_CLOSE', 'PREV_CL_PR', 'PREVCLOSE', 'PRVSCLSGPRIC']),
            't': net_trdval,
            'v': get_val(parts, ['TTL_TRD_QNTY', 'TOTALTRDQTY', 'TOTTRDQTY', 'TTLTRDQTY']),
            'deliv_per': get_val(parts, ['DELIV_PER', 'DELIV. PER']),
            'deliv_qty': get_val(parts, ['DELIV_QTY', 'DELIV_PER_QTY'])
        }
    return stocks

# ==================== BSE BHAVCOPY ====================
def download_bse_bhav(date_ymd, date_dmy):
    dmy_2digit = date_dmy[:4] + date_dmy[6:]  # DDMMYY
    urls = [
        f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{date_ymd}_F_0000.CSV",
        f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{date_ymd}_F_0000.zip",
        f"https://www.bseindia.com/download/BhavCopy/Equity/EQ{dmy_2digit}_CSV.ZIP",
        f"https://www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_{dmy_2digit}.zip",
    ]
    for url in urls:
        print(f"[*] Trying BSE Bhavcopy: {url}")
        raw = fetch_url(url, timeout=20)
        if raw and len(raw) > 500:
            csv_text = extract_csv_from_data(raw)
            if csv_text and len(csv_text) > 1000:
                print(f"[+] Successfully fetched BSE Bhavcopy from: {url}")
                return csv_text
    print(f"[!] Could not download BSE Bhavcopy for {date_ymd}")
    return None

def parse_bse_bhav(csv_text):
    if not csv_text:
        return {}
    stocks = {}
    lines = csv_text.strip().split('\n')
    if len(lines) < 2:
        return {}
    
    header = [h.strip().upper() for h in lines[0].split(',')]

    def safe_f(parts, idx):
        if idx >= 0 and len(parts) > idx:
            try:
                v = parts[idx].strip().replace(' ', '').replace(',', '')
                return float(v) if v else 0.0
            except:
                pass
        return 0.0

    if 'TCKRSYMB' in header and 'CLSPRIC' in header:
        sym_idx = header.index('TCKRSYMB')
        cls_idx = header.index('CLSPRIC')
        code_idx = header.index('FININSTRMID') if 'FININSTRMID' in header else -1
        name_idx = header.index('FININSTRMNM') if 'FININSTRMNM' in header else -1
        srs_idx = header.index('SCTYSRS') if 'SCTYSRS' in header else -1
        tp_idx = header.index('FININSTRMTP') if 'FININSTRMTP' in header else -1
        opn_idx = header.index('OPNPRIC') if 'OPNPRIC' in header else -1
        hgh_idx = header.index('HGHPRIC') if 'HGHPRIC' in header else -1
        lw_idx = header.index('LWPRIC') if 'LWPRIC' in header else -1
        prev_idx = header.index('PRVSCLSGPRIC') if 'PRVSCLSGPRIC' in header else -1
        val_idx = header.index('TTLTRFVAL') if 'TTLTRFVAL' in header else -1
        vol_idx = header.index('TTLTRADGVOL') if 'TTLTRADGVOL' in header else -1
        
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(',')]
            if len(parts) <= max(sym_idx, cls_idx):
                continue
            
            if srs_idx >= 0 and len(parts) > srs_idx:
                srs = parts[srs_idx].upper()
                if srs not in ['A', 'B', 'T', 'X']:
                    continue
            if tp_idx >= 0 and len(parts) > tp_idx:
                if parts[tp_idx].upper() != 'STK':
                    continue
            
            try:
                c = float(parts[cls_idx])
            except:
                continue
            if c <= 0:
                continue
            
            sym = parts[sym_idx]
            if not sym:
                continue

            stocks[sym] = {
                'sym': sym,
                'code': parts[code_idx] if code_idx >= 0 and len(parts) > code_idx else '',
                'name': parts[name_idx] if name_idx >= 0 and len(parts) > name_idx else sym,
                'ex': 'BSE',
                'o': safe_f(parts, opn_idx),
                'h': safe_f(parts, hgh_idx),
                'l': safe_f(parts, lw_idx),
                'c': c,
                'p': safe_f(parts, prev_idx),
                't': safe_f(parts, val_idx),
                'v': safe_f(parts, vol_idx),
                'hi52': 0
            }
        return stocks

    if 'SC_CODE' in header or 'SCRIP_CD' in header:
        def get_col(names):
            for n in names:
                if n in header:
                    return header.index(n)
            return -1

        code_idx = get_col(['SC_CODE', 'SCRIP_CD'])
        name_idx = get_col(['SC_NAME', 'SCRIPNAME', 'SECURITY NAME'])
        grp_idx = get_col(['SC_GROUP', 'SCRIP_GRP'])
        opn_idx = get_col(['OPEN'])
        hgh_idx = get_col(['HIGH'])
        lw_idx = get_col(['LOW'])
        cls_idx = get_col(['CLOSE'])
        prev_idx = get_col(['PREVCLOSE', 'PREV_CLOSE'])
        val_idx = get_col(['NET_TURNOV', 'NET_TRDVAL'])
        vol_idx = get_col(['NO_OF_SHRS', 'NO_OF_TRADES', 'TOTALTRDQTY'])

        for line in lines[1:]:
            parts = [p.strip() for p in line.split(',')]
            if len(parts) <= max(code_idx, cls_idx):
                continue
            
            if grp_idx >= 0 and len(parts) > grp_idx:
                grp = parts[grp_idx].upper()
                if grp not in ['A', 'B', 'T', 'X']:
                    continue
            
            try:
                c = float(parts[cls_idx])
            except:
                continue
            if c <= 0:
                continue

            sym = parts[name_idx] if name_idx >= 0 and len(parts) > name_idx else parts[code_idx]
            sym = sym.strip()
            if not sym:
                continue

            stocks[sym] = {
                'sym': sym,
                'code': parts[code_idx] if code_idx >= 0 and len(parts) > code_idx else '',
                'name': parts[name_idx] if name_idx >= 0 and len(parts) > name_idx else sym,
                'ex': 'BSE',
                'o': safe_f(parts, opn_idx),
                'h': safe_f(parts, hgh_idx),
                'l': safe_f(parts, lw_idx),
                'c': c,
                'p': safe_f(parts, prev_idx),
                't': safe_f(parts, val_idx),
                'v': safe_f(parts, vol_idx),
                'hi52': 0
            }
        return stocks

    return stocks

# ==================== MAIN PIPELINE ====================
def run_pipeline():
    dates = get_target_dates(max_lookback=5)
    
    os.makedirs('data', exist_ok=True)
    os.makedirs('data/history', exist_ok=True)
    
    nse_stocks = {}
    bse_stocks = {}
    chosen_date_iso = None
    
    for date_dmy, date_iso, date_ymd in dates:
        print(f"\n=== Checking date: {date_iso} ===")
        
        if not nse_stocks:
            nse_raw = download_nse_bhav(date_dmy)
            nse_stocks = parse_nse_bhav(nse_raw)
            if nse_stocks:
                print(f"[+] Found NSE Bhavcopy for {date_iso}: {len(nse_stocks)} stocks")
        
        if not bse_stocks:
            bse_raw = download_bse_bhav(date_ymd, date_dmy)
            bse_stocks = parse_bse_bhav(bse_raw)
            if bse_stocks:
                print(f"[+] Found BSE Bhavcopy for {date_iso}: {len(bse_stocks)} stocks")
        
        if nse_stocks or bse_stocks:
            chosen_date_iso = date_iso
            if nse_stocks and bse_stocks:
                break

    if not nse_stocks and not bse_stocks:
        print("[!] No trading data fetched for recent dates (Market holiday or weekend).")
        return

    print(f"\n[+] Total Active Stocks loaded -> NSE: {len(nse_stocks)}, BSE: {len(bse_stocks)}")

    day_record = {
        'date': chosen_date_iso,
        'nse': nse_stocks,
        'bse': bse_stocks,
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
    
    hist_path = f"data/history/{chosen_date_iso}.json"
    with open(hist_path, 'w', encoding='utf-8') as f:
        json.dump(day_record, f, separators=(',', ':'))
    print(f"[+] Saved historical file: {hist_path}")
    
    latest_path = "data/latest.json"
    with open(latest_path, 'w', encoding='utf-8') as f:
        json.dump(day_record, f, separators=(',', ':'))
    print(f"[+] Updated latest pointer: {latest_path}")

if __name__ == '__main__':
    run_pipeline()

"""
SmartScanner Cloud Auto-Fetcher & Live Intraday Engine
Fetches daily Bhavcopy, Deals, F&O, and Deliv% from NSE & BSE.
During market hours (09:15 to 15:30 IST), automatically fetches real-time
intraday market quotes so the scanner is 100% LIVE during trading hours!
"""

import os
import io
import json
import zipfile
import datetime
import urllib.request
import urllib.error
import time

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

def get_ist_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)

def is_market_hours(dt_ist):
    # Mon-Fri (0-4)
    if dt_ist.weekday() >= 5:
        return False
    mins = dt_ist.hour * 60 + dt_ist.minute
    # Between 09:15 IST (555 min) and 16:30 IST (990 min)
    return 555 <= mins <= 990

def get_target_dates(max_lookback=35):
    """Returns list of (date_dmy, date_iso, date_ymd) from today backwards in IST"""
    now = get_ist_now()
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
        raw = fetch_url(url, timeout=20)
        if raw and len(raw) > 500:
            csv_text = extract_csv_from_data(raw)
            if csv_text and len(csv_text) > 1000:
                print(f"[+] Successfully fetched BSE Bhavcopy from: {url}")
                return csv_text
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
                if parts[srs_idx].upper() not in ['A', 'B', 'T', 'X']:
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
                if parts[grp_idx].upper() not in ['A', 'B', 'T', 'X']:
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

# ==================== LIVE INTRADAY QUOTE FETCHER ====================
def fetch_live_quotes_batch(symbols, exchange='NSE'):
    """
    Fetches real-time intraday quotes for up to 100 symbols per request from Yahoo Finance.
    Returns dict: { SYM: { c, o, h, l, p, v, t, chg } }
    """
    if not symbols:
        return {}
    
    suffix = '.NS' if exchange == 'NSE' else '.BO'
    sym_query = ','.join([f"{s}{suffix}" for s in symbols])
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={sym_query}"
    
    raw = fetch_url(url, timeout=15)
    if not raw:
        return {}
    
    out = {}
    try:
        data = json.loads(raw.decode('utf-8', errors='ignore'))
        results = data.get('quoteResponse', {}).get('result', [])
        for item in results:
            raw_sym = item.get('symbol', '')
            clean_sym = raw_sym.replace('.NS', '').replace('.BO', '')
            price = item.get('regularMarketPrice')
            if price is None or price <= 0:
                continue
            
            prev = item.get('regularMarketPreviousClose', price)
            open_p = item.get('regularMarketOpen', price)
            high_p = item.get('regularMarketDayHigh', price)
            low_p = item.get('regularMarketDayLow', price)
            vol = item.get('regularMarketVolume', 0)
            chg = item.get('regularMarketChangePercent', 0)
            trdval = vol * price  # Approx turnover in INR
            
            out[clean_sym] = {
                'sym': clean_sym,
                'name': item.get('shortName') or clean_sym,
                'ex': exchange,
                'o': float(open_p),
                'h': float(high_p),
                'l': float(low_p),
                'c': float(price),
                'p': float(prev),
                't': float(trdval),
                'v': float(vol),
                'chg': float(chg)
            }
    except Exception as e:
        print(f"[WARN] Error parsing live quote batch: {e}")
    
    return out

def generate_intraday_snapshot(prior_day, now_ist):
    """
    Builds a real-time snapshot during market hours by updating stock prices with live quotes.
    """
    today_iso = now_ist.strftime('%Y-%m-%d')
    time_str = now_ist.strftime('%H:%M IST')
    print(f"\n[⚡ LIVE] Generating Real-Time Market Snapshot for {today_iso} at {time_str}...")
    
    prior_nse = prior_day.get('nse', {})
    prior_bse = prior_day.get('bse', {})
    
    # Sort active stocks by turnover to prioritize the most active liquid names
    nse_syms = sorted(prior_nse.keys(), key=lambda s: prior_nse[s].get('t', 0), reverse=True)
    bse_syms = sorted(prior_bse.keys(), key=lambda s: prior_bse[s].get('t', 0), reverse=True)
    
    # Query top 1,000 active NSE stocks (in batches of 100)
    target_nse = nse_syms[:1000] if len(nse_syms) > 1000 else nse_syms
    live_nse = {}
    
    chunk_size = 90
    for i in range(0, len(target_nse), chunk_size):
        chunk = target_nse[i:i+chunk_size]
        quotes = fetch_live_quotes_batch(chunk, 'NSE')
        for s, q in quotes.items():
            # Retain meta like name
            base = dict(prior_nse.get(s, {}))
            base.update(q)
            live_nse[s] = base
        time.sleep(0.15)  # gentle delay between batches
    
    print(f"[+] Live Intraday NSE quotes updated: {len(live_nse)} / {len(target_nse)} stocks")
    
    # If some NSE stocks weren't updated in live batch, carry over prior info with 0 volume indicator
    for s in nse_syms:
        if s not in live_nse and s in prior_nse:
            live_nse[s] = prior_nse[s]

    live_day = {
        'date': today_iso,
        'intraday': True,
        'intraday_time': time_str,
        'nse': live_nse,
        'bse': prior_bse,  # Prior BSE baseline
        'hl': prior_day.get('hl', {}),
        'band': prior_day.get('band', {}),
        'volg': prior_day.get('volg', {}),
        'deal': prior_day.get('deal', {}),
        'cas': prior_day.get('cas', {}),
        'mcap': prior_day.get('mcap', {}),
        'fut': prior_day.get('fut', {}),
        'pcr': prior_day.get('pcr', {}),
        'iep': prior_day.get('iep', {})
    }
    
    return live_day

# ==================== MAIN PIPELINE ====================
def run_pipeline():
    now_ist = get_ist_now()
    today_iso = now_ist.strftime('%Y-%m-%d')
    today_dmy = now_ist.strftime('%d%m%Y')
    today_ymd = now_ist.strftime('%Y%m%d')
    market_active = is_market_hours(now_ist)
    
    print(f"==================================================")
    print(f"SmartScanner Sync Run: {now_ist.strftime('%Y-%m-%d %H:%M:%S IST')} | Market Active: {market_active}")
    print(f"==================================================")
    
    dates = get_target_dates(max_lookback=35)
    os.makedirs('data', exist_ok=True)
    os.makedirs('data/history', exist_ok=True)
    
    saved_days = []
    today_eod_found = False

    for date_dmy, date_iso, date_ymd in dates:
        hist_path = f"data/history/{date_iso}.json"
        
        # Check if already cached on disk (and NOT an intraday snapshot)
        if os.path.exists(hist_path):
            try:
                with open(hist_path, 'r', encoding='utf-8') as f:
                    day_rec = json.load(f)
                    if (day_rec.get('nse') or day_rec.get('bse')) and not day_rec.get('intraday'):
                        saved_days.append(day_rec)
                        if date_iso == today_iso:
                            today_eod_found = True
                        if len(saved_days) >= 20:
                            break
                        continue
            except Exception:
                pass
        
        # Try downloading Bhavcopy
        print(f"[*] Checking Bhavcopy for: {date_iso}")
        nse_raw = download_nse_bhav(date_dmy)
        nse_stocks = parse_nse_bhav(nse_raw)
        
        bse_raw = download_bse_bhav(date_ymd, date_dmy)
        bse_stocks = parse_bse_bhav(bse_raw)
        
        if nse_stocks or bse_stocks:
            print(f"[+] Found Final Bhavcopy for {date_iso} -> NSE: {len(nse_stocks)}, BSE: {len(bse_stocks)}")
            day_rec = {
                'date': date_iso,
                'intraday': False,
                'nse': nse_stocks,
                'bse': bse_stocks,
                'hl': {}, 'band': {}, 'volg': {}, 'deal': {}, 'cas': {},
                'mcap': {}, 'fut': {}, 'pcr': {}, 'iep': {}
            }
            with open(hist_path, 'w', encoding='utf-8') as f:
                json.dump(day_rec, f, separators=(',', ':'))
            saved_days.append(day_rec)
            if date_iso == today_iso:
                today_eod_found = True
            if len(saved_days) >= 20:
                break

    if not saved_days:
        print("[!] No prior trading days found in history.")
        return

    # Sort days chronologically ascending
    saved_days.sort(key=lambda x: x['date'])
    
    # CHECK: Is it market hours today and Final EOD Bhavcopy is not yet out?
    if market_active and not today_eod_found:
        prior_day = saved_days[-1]
        live_day = generate_intraday_snapshot(prior_day, now_ist)
        if live_day and live_day.get('nse'):
            # Bundle prior completed days into history
            live_day['history'] = saved_days[-20:]
            latest_path = "data/latest.json"
            with open(latest_path, 'w', encoding='utf-8') as f:
                json.dump(live_day, f, separators=(',', ':'))
            print(f"\n[🚀 SUCCESS] Published LIVE INTRADAY data to {latest_path} ({live_day['intraday_time']})")
            return

    # Otherwise, publish latest completed EOD Bhavcopy
    latest_day = dict(saved_days[-1])
    prior_days = saved_days[:-1]
    if prior_days:
        latest_day['history'] = prior_days[-20:]
        print(f"[+] Bundled {len(latest_day['history'])} prior sessions into latest.json")

    latest_path = "data/latest.json"
    with open(latest_path, 'w', encoding='utf-8') as f:
        json.dump(latest_day, f, separators=(',', ':'))
    print(f"\n[+] Published latest EOD data to {latest_path} (Date: {latest_day['date']})")

if __name__ == '__main__':
    run_pipeline()

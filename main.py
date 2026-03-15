import telebot
import requests
import numpy as np
import matplotlib.pyplot as plt
import io
import time
import threading 
import re 
import os 
from keep_alive import keep_alive 

# Chạy ngầm vẽ hình
plt.switch_backend('Agg') 

# --- CẤU HÌNH ---
API_TOKEN = os.environ.get('BOT_TOKEN')
if not API_TOKEN:
    API_TOKEN = '7964594688:AAGPv7UiXdhm0O3mLjRoOxMDNJbrS3vEAmM'

bot = telebot.TeleBot(API_TOKEN)

WATCHLIST_MARKET = ['BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'DOGE', 'ADA', 'AVAX', 'LINK', 'LTC', 'DOT', 'MATIC', 'TRX', 'SHIB', 'NEAR', 'PEPE', 'WIF', 'BONK', 'ARB', 'OP', 'SUI', 'APT', 'FIL', 'ATOM', 'FTM', 'SAND']

USER_DATA = {}
TY_GIA_USDT_CACHE = 26000 

def get_user_data(chat_id):
    if chat_id not in USER_DATA:
        USER_DATA[chat_id] = {
            'balance': 500000,    
            'bet_amount': 50000,  # Ít dùng vì SMC auto 1% risk
            'is_all_in': False,   
            'currency': 'VNDC',   
            'watching': [],       
            'auto_watching': [],  
            'active_trades': {},
            'stats': {'wins': 0, 'losses': 0},
            'is_monitoring': False 
        }
    return USER_DATA[chat_id]

def fmt_money(amount, currency):
    if currency == 'USDT':
        return f"${amount:,.2f}"
    return f"{amount:,.0f} đ"

def lay_ty_gia_remitano():
    try:
        url = "https://api.remitano.com/api/v1/rates/ads"
        res = requests.get(url, timeout=3).json()
        if 'usdt' in res: return float(res['usdt']['ask'])
    except: pass
    return 26000

# --- LẤY DATA BINANCE M5 ---
def lay_data_binance(symbol, limit=500):
    NODES = [
        "https://fapi.binance.com/fapi/v1/klines", 
        "https://api.binance.com/api/v3/klines", 
        "https://api1.binance.com/api/v3/klines",
        "https://api2.binance.com/api/v3/klines"
    ]
    pair = symbol.upper() + "USDT"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    for url_base in NODES:
        try:
            # Lấy nến 5m (M5)
            url = f"{url_base}?symbol={pair}&interval=5m&limit={limit}"
            data = requests.get(url, headers=headers, timeout=5).json()
            if isinstance(data, list) and len(data) > 0:
                opens = [float(x[1]) for x in data]
                highs = [float(x[2]) for x in data]
                lows = [float(x[3]) for x in data]
                closes = [float(x[4]) for x in data]
                volumes = [float(x[5]) for x in data]
                src_name = "Futures ⚡" if "fapi" in url_base else "Spot"
                return np.array(opens), np.array(highs), np.array(lows), np.array(closes), np.array(volumes), src_name
        except: continue
    return None, None, None, None, None, None

def lay_data_lich_su(symbol, days=7):
    try:
        pair = symbol.upper() + "USDT"
        limit_per_req = 1000
        total_candles = days * 288 # M5 = 288 nến/ngày
        rounds = int(total_candles / limit_per_req) + 2
        all_open, all_high, all_low, all_close, all_vol = [], [], [], [], []
        end_time = int(time.time() * 1000) 
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        for _ in range(rounds):
            url = f"https://fapi.binance.com/fapi/v1/klines?symbol={pair}&interval=5m&limit={limit_per_req}&endTime={end_time}"
            data = requests.get(url, headers=headers, timeout=5).json()
            if not isinstance(data, list) or len(data) == 0: break
            
            opens = [float(x[1]) for x in data]
            highs = [float(x[2]) for x in data]
            lows = [float(x[3]) for x in data]
            closes = [float(x[4]) for x in data]
            vols = [float(x[5]) for x in data]
            
            all_open = opens + all_open
            all_high = highs + all_high
            all_low = lows + all_low
            all_close = closes + all_close
            all_vol = vols + all_vol
            end_time = data[0][0] - 1
            time.sleep(0.05) 
        return np.array(all_open), np.array(all_high), np.array(all_low), np.array(all_close), np.array(all_vol), len(all_close)
    except: pass
    return None, None, None, None, None, 0

# --- SMC ANALYSIS LOGIC ---
def find_swing_points(highs, lows, lookback):
    swing_highs = []
    swing_lows = []
    for i in range(lookback, len(highs) - lookback):
        if highs[i] == np.max(highs[i-lookback:i+lookback+1]):
            swing_highs.append((i, highs[i]))
        if lows[i] == np.min(lows[i-lookback:i+lookback+1]):
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows

def check_smc_setup(opens, highs, lows, closes, vols, i):
    # Chặn dữ liệu từ hiện tại trở về trước
    c_h = highs[:i+1]
    c_l = lows[:i+1]
    c_c = closes[:i+1]
    c_o = opens[:i+1]
    c_v = vols[:i+1]

    if len(c_c) < 150: return None, 0, 0, "" # Cần đủ data

    # 1. Volume Check M5
    vol_sma20 = np.mean(c_v[-20:])
    curr_vol = c_v[-1]
    
    # 2. Xây dựng Nến M15 từ M5 (Gộp 3 nến)
    m15_h, m15_l, m15_c, m15_o = [], [], [], []
    for j in range(len(c_c)-1, -1, -3):
        if j-2 < 0: break
        m15_h.append(np.max(c_h[j-2:j+1]))
        m15_l.append(np.min(c_l[j-2:j+1]))
        m15_c.append(c_c[j])
        m15_o.append(c_o[j-2])

    m15_h, m15_l, m15_c, m15_o = np.array(m15_h[::-1]), np.array(m15_l[::-1]), np.array(m15_c[::-1]), np.array(m15_o[::-1])

    # 3. Swing Points M15 (Lookback 15) & M5 (Lookback 10)
    m15_sw_h, m15_sw_l = find_swing_points(m15_h, m15_l, 15)
    m5_sw_h, m5_sw_l = find_swing_points(c_h, c_l, 10)

    if len(m15_sw_h) < 2 or len(m15_sw_l) < 2 or len(m5_sw_h) < 1 or len(m5_sw_l) < 1:
        return None, 0, 0, ""

    curr_h, curr_l, curr_c, curr_o = c_h[-1], c_l[-1], c_c[-1], c_o[-1]

    # 4. Kiểm tra Liquidity Sweep M5 (Quét râu nhưng đóng nến rút chân)
    is_bullish_sweep = False
    for _, val in m5_sw_l[-5:]: # Kiểm tra các đáy thanh khoản gần nhất
        if curr_l < val and curr_c > val: # Thủng râu, đóng trên
            is_bullish_sweep = True
            break

    is_bearish_sweep = False
    for _, val in m5_sw_h[-5:]:
        if curr_h > val and curr_c < val: # Chọc râu lên, đóng dưới
            is_bearish_sweep = True
            break

    # Nếu không có Quét Thanh Khoản Hoặc Volume Tạch -> Bỏ qua nhanh
    if not is_bullish_sweep and not is_bearish_sweep:
        return None, 0, 0, ""
    if curr_vol <= 1.5 * vol_sma20:
        return None, 0, 0, ""

    # 5. Xác định Trend M15
    last_h1, last_h2 = m15_sw_h[-1][1], m15_sw_h[-2][1]
    last_l1, last_l2 = m15_sw_l[-1][1], m15_sw_l[-2][1]
    uptrend = (last_h1 > last_h2) and (last_l1 > last_l2)
    downtrend = (last_h1 < last_h2) and (last_l1 < last_l2)

    # 6. Tính FVG M15
    atr_14 = np.mean(m15_h[-14:] - m15_l[-14:])
    bullish_fvgs, bearish_fvgs = [], []
    
    # Quét 50 nến M15 gần nhất
    start_idx = max(0, len(m15_h) - 50)
    for j in range(start_idx, len(m15_h) - 2):
        # Bullish FVG
        gap_up = m15_l[j+2] - m15_h[j]
        if gap_up > 0.5 * atr_14:
            filled = any(m15_l[k] < m15_h[j] for k in range(j+3, len(m15_h)))
            if not filled: bullish_fvgs.append((m15_h[j], m15_l[j+2]))
        
        # Bearish FVG
        gap_down = m15_l[j] - m15_h[j+2]
        if gap_down > 0.5 * atr_14:
            filled = any(m15_h[k] > m15_l[j] for k in range(j+3, len(m15_h)))
            if not filled: bearish_fvgs.append((m15_h[j+2], m15_l[j]))

    tin_hieu, sl, tp, ly_do = None, 0, 0, ""

    # --- SETUP LONG ---
    if is_bullish_sweep and uptrend:
        # Hợp lưu FVG
        in_fvg = any(fvg[0] <= curr_l <= fvg[1] for fvg in bullish_fvgs)
        
        # Hợp lưu Support
        near_supp = any(abs(curr_l - l[1])/l[1] < 0.002 for l in m15_sw_l[-3:])
        
        # Hợp lưu Fib 0.618 - 0.786
        wave_l, wave_h = m15_sw_l[-1][1], m15_sw_h[-1][1]
        if m15_sw_l[-1][0] > m15_sw_h[-1][0]: wave_h = m15_sw_h[-2][1] if len(m15_sw_h)>1 else wave_h
        
        fib_618 = wave_h - 0.618*(wave_h - wave_l)
        fib_786 = wave_h - 0.786*(wave_h - wave_l)
        in_fib = (fib_786 <= curr_l <= fib_618)
        
        # Yêu cầu FVG + (Fib hoặc Support)
        if in_fvg and (in_fib or near_supp):
            tin_hieu = "LONG (SMC) 🟢"
            ly_do = "M15 Uptrend + FVG + M5 Liq Sweep + Vol Đột Biến"
            sl = curr_l * 0.9995 # SL dưới râu quét 1 chút
            tp = curr_c + (curr_c - sl) * 2.0 # R:R 1:2

    # --- SETUP SHORT ---
    elif is_bearish_sweep and downtrend:
        in_fvg = any(fvg[0] <= curr_h <= fvg[1] for fvg in bearish_fvgs)
        near_res = any(abs(curr_h - h[1])/h[1] < 0.002 for h in m15_sw_h[-3:])
        
        wave_h, wave_l = m15_sw_h[-1][1], m15_sw_l[-1][1]
        if m15_sw_h[-1][0] > m15_sw_l[-1][0]: wave_l = m15_sw_l[-2][1] if len(m15_sw_l)>1 else wave_l
        
        fib_618 = wave_l + 0.618*(wave_h - wave_l)
        fib_786 = wave_l + 0.786*(wave_h - wave_l)
        in_fib = (fib_618 <= curr_h <= fib_786)
        
        if in_fvg and (in_fib or near_res):
            tin_hieu = "SHORT (SMC) 🔴"
            ly_do = "M15 Downtrend + FVG + M5 Liq Sweep + Vol Đột Biến"
            sl = curr_h * 1.0005
            tp = curr_c - (sl - curr_c) * 2.0

    return tin_hieu, sl, tp, ly_do

# --- BACKTEST (x30 LEVERAGE + RISK 1%) ---
def process_backtest(chat_id, symbol, start_capital, days):
    user = get_user_data(chat_id)
    try:
        opens, highs, lows, closes, vols, count = lay_data_lich_su(symbol, days=days)
        if closes is None or len(closes) < 150:
            bot.send_message(chat_id, f"❌ Không đủ dữ liệu M5 để chạy SMC.")
            return

        balance = start_capital
        leverage = 30 # x30
        wins, losses = 0, 0
        active_trade = None
        
        for i in range(150, len(closes)-1):
            if active_trade:
                curr_h, curr_l = highs[i], lows[i]
                res = None
                
                if active_trade['type'] == 'LONG':
                    if curr_h >= active_trade['tp']: res = 'WIN'
                    if curr_l <= active_trade['sl']: res = 'LOSS'
                else: 
                    if curr_l <= active_trade['tp']: res = 'WIN'
                    if curr_h >= active_trade['sl']: res = 'LOSS'
                
                if res:
                    entry = active_trade['entry']
                    amt = active_trade['amount']
                    close_p = active_trade['tp'] if res == 'WIN' else active_trade['sl']
                    
                    move = (close_p - entry)/entry if active_trade['type'] == 'LONG' else (entry - close_p)/entry
                    pnl = move * leverage * amt
                    
                    balance += pnl
                    if res == 'WIN': wins += 1
                    else: losses += 1
                    
                    if balance < 0: balance = 0
                    active_trade = None
                continue
            
            if balance <= (start_capital * 0.05): break 
            
            tin_hieu, sl, tp, ly_do = check_smc_setup(opens, highs, lows, closes, vols, i)
            
            if tin_hieu:
                # Quản lý vốn 1% Risk
                risk_amt = balance * 0.01
                entry = closes[i]
                dist_pct = abs(entry - sl) / entry
                if dist_pct == 0: dist_pct = 0.001
                
                pos_size = risk_amt / dist_pct
                margin_needed = pos_size / leverage
                
                if margin_needed > balance: margin_needed = balance
                
                active_trade = {
                    'type': 'LONG' if 'LONG' in tin_hieu else 'SHORT',
                    'entry': entry, 'sl': sl, 'tp': tp, 
                    'amount': margin_needed # Margin
                }

        total_trades = wins + losses
        win_rate = (wins/total_trades * 100) if total_trades > 0 else 0
        pnl_total = balance - start_capital
        emoji = "🤑 LÃI" if pnl_total >= 0 else "🩸 LỖ"
        if balance < (start_capital * 0.05): emoji = "💀 CHÁY TK"

        msg = (
            f"📊 **BACKTEST SMC ICT ({days} NGÀY) - M5/M15**\n"
            f"Coin: **{symbol}**\n"
            f"Số nến M5: {count}\n"
            f"--------------------------\n"
            f"💵 Vốn đầu: {fmt_money(start_capital, user['currency'])}\n"
            f"🏁 Vốn cuối: {fmt_money(balance, user['currency'])}\n"
            f"📈 **P&L: {fmt_money(pnl_total, user['currency'])}** ({emoji})\n"
            f"--------------------------\n"
            f"🏆 Thắng: {wins} | 🥀 Thua: {losses}\n"
            f"🔄 Tổng lệnh: {total_trades}\n"
            f"💎 **Tỷ lệ Win: {win_rate:.1f}%**\n"
            f"⚠️ **Cơ chế:** Quản lý vốn Risk 1% / Lệnh - R:R 1:2"
        )
        bot.send_message(chat_id, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Lỗi: {e}")

# --- VẼ CHART M5 SMC ---
def ve_chart(symbol, opens, highs, lows, closes, vols):
    view = 60 
    p_c = closes[-view:]
    v_v = vols[-view:]
    
    vol_sma = np.array([np.mean(vols[i-20:i]) for i in range(len(vols)-view, len(vols))])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 10), gridspec_kw={'height_ratios': [3, 2]})
    fig.tight_layout(pad=5.0)

    # Chart Giá
    ax1.plot(p_c, color='black', alpha=0.8, label='M5 Price')
    
    # Đánh dấu Liquidity Low/High gần nhất
    recent_l = np.min(lows[-15:])
    recent_h = np.max(highs[-15:])
    ax1.axhline(recent_l, color='red', linestyle='--', alpha=0.5, label='Liquidity Sweep Zone')
    ax1.axhline(recent_h, color='green', linestyle='--', alpha=0.5)

    ax1.set_title(f'{symbol} (M5) SMC Liquidity')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.2)

    # Chart Volume
    colors = ['green' if closes[-view+i] > opens[-view+i] else 'red' for i in range(view)]
    ax2.bar(range(view), v_v, color=colors, alpha=0.6, label='Volume')
    ax2.plot(vol_sma, color='orange', label='Vol SMA 20')
    ax2.set_title('M5 Volume Check (>1.5x SMA)')
    ax2.legend(loc='upper left')
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

# --- EXECUTE ---
def scan_market(chat_id):
    bot.send_message(chat_id, "📡 **Đang quét SMC (M5/M15) Chờ xíu nhé...**", parse_mode="Markdown")
    signals = []
    for symbol in WATCHLIST_MARKET:
        opens, highs, lows, closes, vols, _ = lay_data_binance(symbol)
        if closes is not None:
            tin_hieu, _, _, _ = check_smc_setup(opens, highs, lows, closes, vols, -1)
            if tin_hieu:
                signals.append(f"🔥 {symbol}: {tin_hieu}")
    return signals[:10]

def execute_trade(chat_id, symbol, tin_hieu, ly_do, entry, sl, tp):
    user = get_user_data(chat_id)
    if user['balance'] <= 0:
        bot.send_message(chat_id, "❌ **Hết tiền Demo rồi! Vui lòng nạp thêm vốn bằng lệnh /Von**")
        return
    
    # Quản lý rủi ro (Position Sizing SMC)
    risk_amount = user['balance'] * 0.01 # Mặc định Risk 1%
    dist_pct = abs(entry - sl) / entry
    if dist_pct == 0: dist_pct = 0.001
    
    pos_size = risk_amount / dist_pct
    margin_needed = pos_size / 30 # Leverage x30
    
    note = " (Risk 1% SMC)"
    
    if user.get('is_all_in', False):
        margin_needed = user['balance']
        note = " (ALL-IN CHÁY MÁY 🔥)"

    if margin_needed > user['balance']: 
        margin_needed = user['balance']

    user['balance'] -= margin_needed
    
    user['active_trades'][symbol] = {
        'type': 'LONG' if 'LONG' in tin_hieu else 'SHORT',
        'entry': entry, 'sl': sl, 'tp': tp, 
        'amount': margin_needed, 'leverage': 30 
    }
    
    msg = (
        f"🚀 **ENTRY SMC: {symbol}**\n--------------------\n"
        f"Loại: **{tin_hieu}**\nLý do: {ly_do}\n--------------------\n"
        f"Entry: **${entry:,.4f}**\n"
        f"Ký quỹ: **{fmt_money(margin_needed, user['currency'])}**{note}\n"
        f"🛑 SL: **${sl:,.4f}**\n🎯 TP: **${tp:,.4f}**\n"
        f"--------------------\n💰 Còn lại: {fmt_money(user['balance'], user['currency'])}"
    )
    bot.send_message(chat_id, msg, parse_mode="Markdown")

# --- MONITOR 24/7 ---
def monitor_thread(chat_id):
    bot.send_message(chat_id, "🤖 Bot bắt đầu vào chế độ SMC Sniper M5/M15...")
    while True:
        try: 
            user = get_user_data(chat_id)
            if not user['watching'] and not user['active_trades'] and not user['auto_watching']: 
                time.sleep(10)
                continue

            current_watching = list(user['watching']) 
            for symbol in current_watching:
                try: 
                    opens, highs, lows, closes, vols, _ = lay_data_binance(symbol)
                    if closes is not None:
                        tin_hieu, sl, tp, ly_do = check_smc_setup(opens, highs, lows, closes, vols, -1)
                        if tin_hieu and symbol not in user['active_trades']:
                            execute_trade(chat_id, symbol, tin_hieu, ly_do, closes[-1], sl, tp)
                            if symbol in user['watching']: user['watching'].remove(symbol)
                except: pass

            current_auto = list(user['auto_watching']) 
            for symbol in current_auto:
                try: 
                    if symbol in user['active_trades']: continue 

                    opens, highs, lows, closes, vols, _ = lay_data_binance(symbol)
                    if closes is not None:
                        tin_hieu, sl, tp, ly_do = check_smc_setup(opens, highs, lows, closes, vols, -1)
                        if tin_hieu:
                            execute_trade(chat_id, symbol, tin_hieu, ly_do, closes[-1], sl, tp)
                except: pass
            
            active_symbols = list(user['active_trades'].keys())
            for symbol in active_symbols:
                try:
                    trade = user['active_trades'][symbol]
                    _, highs, lows, closes, _, _ = lay_data_binance(symbol)
                    if closes is not None:
                        curr_h, curr_l = highs[-1], lows[-1]
                        
                        hit_tp, hit_sl = False, False
                        
                        if trade['type'] == 'LONG':
                            if curr_h >= trade['tp']: hit_tp = True
                            if curr_l <= trade['sl']: hit_sl = True
                        else: 
                            if curr_l <= trade['tp']: hit_tp = True
                            if curr_h >= trade['sl']: hit_sl = True
                        
                        if hit_tp or hit_sl:
                            if hit_tp and hit_sl: hit_tp = False
                            
                            close_price = trade['tp'] if hit_tp else trade['sl']
                            
                            if trade['type'] == 'LONG':
                                move = (close_price - trade['entry']) / trade['entry']
                            else: 
                                move = (trade['entry'] - close_price) / trade['entry']
                            
                            pnl = move * trade['leverage'] * trade['amount']
                            
                            user['balance'] += (trade['amount'] + pnl)
                            ket_qua = "WIN 🟢" if hit_tp else "LOSS 🔴"
                            if hit_tp: user['stats']['wins'] += 1
                            else: user['stats']['losses'] += 1
                            
                            is_auto_trade = (symbol in user['auto_watching'])
                            auto_msg = "\n🔄 Tiếp tục rình mồi..." if is_auto_trade else "\n🏁 Đã dừng theo dõi."
                            pnl_sign = "+" if pnl >= 0 else ""
                            
                            msg_to_send = f"🔔 **CHỐT SMC {symbol}: {ket_qua}**\nLãi/Lỗ: {pnl_sign}{fmt_money(pnl, user['currency'])}\n💰 Vốn mới: {fmt_money(user['balance'], user['currency'])}{auto_msg}"
                            
                            del user['active_trades'][symbol]
                            bot.send_message(chat_id, msg_to_send, parse_mode="Markdown")
                except: pass

            time.sleep(60) 
        except:
            time.sleep(10)

def check_all_in_safety(user, message, coins_to_add=[]):
    if user.get('is_all_in', False):
        current_coins = set(list(user['active_trades'].keys()) + user['watching'] + user['auto_watching'])
        new_total = len(current_coins.union(set(coins_to_add)))
        if new_total > 1:
            bot.reply_to(message, "⚠️ **CHÚ Ý:** Bạn đang bật `Cuoc all`. CHỈ ĐƯỢC canh 1 coin duy nhất. Hãy gõ `Dung` để xóa list trước!")
            return False
    return True

# --- BOT COMMANDS ---
@bot.message_handler(commands=['start', 'help'])
def send_help(message):
    user = get_user_data(message.chat.id)
    help_text = (
        "📖 **HƯỚNG DẪN BOT SMC (SMART MONEY CONCEPTS)** 📖\n\n"
        "🛠 **1. CÀI ĐẶT VỐN & ĐA VÍ:**\n"
        "   👉 `/Von VNDC 1000000`: Set vốn VNĐ.\n"
        "   👉 `/Von USDT 50`: Set vốn USD.\n"
        "   👉 `/Chuyen USDT` (hoặc VNDC): Tự động đổi số dư sang ví mới.\n"
        "   👉 `/Cuoc all`: Đánh 100% vốn.\n"
        "   ℹ️ *Mặc định Bot tự động đánh Risk 1% tài khoản chuẩn Quỹ.*\n\n"
        "🧪 **2. BACKTEST SMC:**\n"
        "   👉 `Backtest [Coin] Von [Tiền]`: Test 7 ngày.\n\n"
        "🚀 **3. SĂN KÈO SMC (M5/M15):**\n"
        "   👉 `Entry now [Coin]`: Vào lệnh tay.\n"
        "   👉 `Scan`: Quét 10 coin FVG/Liquidity.\n"
        "   👉 `Theo doi [Coin]`: Canh tín hiệu -> Đánh -> Dừng.\n"
        "   👉 `/Auto [Coin]`: Canh 24/7 (Săn thanh khoản liên tục).\n\n"
        "📊 **4. TIỆN ÍCH:**\n"
        "   👉 `Thong ke` / `Reset thong ke`.\n"
        "   👉 `Xem theo doi` / `Dung`.\n"
        "   👉 Nhập tên Coin để xem Chart M5 SMC.\n\n"
        "--------------------------\n"
        f"💳 Đang dùng ví: **{user['currency']}**\n"
        f"💰 Vốn: **{fmt_money(user['balance'], user['currency'])}**\n"
        f"💵 Chế độ cược: **{'ALL-IN (100%)' if user['is_all_in'] else 'Risk 1% SMC'}**"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['Auto', 'auto'])
def handle_auto(message):
    try:
        coins = message.text.replace("/Auto", "").replace("/auto", "").strip().upper().replace(",", " ").split()
        if not coins: return bot.reply_to(message, "⚠️ Nhập tên coin. VD: `/Auto BTC ETH`")
        
        chat_id = message.chat.id
        user = get_user_data(chat_id)
        if not check_all_in_safety(user, message, coins): return

        added = []
        for c in coins:
            if c not in user['auto_watching']:
                user['auto_watching'].append(c)
                added.append(c)
                if c in user['watching']: user['watching'].remove(c)

        if added:
            bot.reply_to(message, f"🔄 Đã bật chế độ **AUTO SMC 24/7** cho: {', '.join(added)}", parse_mode="Markdown")
            if not user.get('is_monitoring', False):
                user['is_monitoring'] = True
                threading.Thread(target=monitor_thread, args=(chat_id,), daemon=True).start()
    except Exception as e: bot.reply_to(message, f"Lỗi: {e}")

@bot.message_handler(func=lambda message: True)
def handle_msg(message):
    text = message.text.strip().upper()
    chat_id = message.chat.id
    user = get_user_data(chat_id)
    
    if text.startswith("VON ") or text.startswith("VỐN "):
        parts = text.split()
        if len(parts) >= 3 and parts[1] in ["VNDC", "USDT"]:
            curr = parts[1]
            try:
                val = float(parts[2].replace(',', ''))
                user['currency'] = curr
                user['balance'] = val
                bot.reply_to(message, f"✅ Đã set lại ví: **{curr}**\n💰 Vốn: **{fmt_money(val, curr)}**", parse_mode="Markdown")
            except: pass
            return
        elif len(parts) == 2:
            try:
                val = float(parts[1].replace(',', ''))
                user['balance'] = val
                bot.reply_to(message, f"✅ Đã set vốn: **{fmt_money(val, user['currency'])}**", parse_mode="Markdown")
            except: pass
            return

    if text.startswith("CHUYEN ") or text.startswith("CHUYỂN "):
        parts = text.split()
        if len(parts) >= 2:
            target_curr = parts[1].upper()
            if target_curr in ["VNDC", "USDT"] and target_curr != user['currency']:
                ty_gia = lay_ty_gia_remitano() or 26000
                if target_curr == 'USDT':
                    user['balance'] = user['balance'] / ty_gia
                else:
                    user['balance'] = user['balance'] * ty_gia
                
                user['currency'] = target_curr
                bot.reply_to(message, f"💱 Đã CHUYỂN ĐỔI ví sang **{target_curr}**.\n💰 Vốn mới: **{fmt_money(user['balance'], target_curr)}**", parse_mode="Markdown")
            return

    if text.startswith("CUOC ") or text.startswith("CƯỢC "):
        parts = text.split()
        if len(parts) >= 2:
            if parts[1] == "ALL":
                user['is_all_in'] = True
                bot.reply_to(message, f"🔥 Đã kích hoạt **CƯỢC ALL-IN** (100% vốn).", parse_mode="Markdown")
            else:
                user['is_all_in'] = False
                bot.reply_to(message, "✅ Đã tắt ALL-IN. Chuyển về tính năng **Risk 1% theo SMC**.", parse_mode="Markdown")
        return

    if text in ["XEM VON", "VỐN"]:
        bot.reply_to(message, f"💳 Ví: **{user['currency']}**\n💰 Vốn: **{fmt_money(user['balance'], user['currency'])}**\n💵 Chế độ cược: **{'ALL-IN' if user['is_all_in'] else 'Risk 1% SMC'}**", parse_mode="Markdown")
        return

    if text.startswith("BACKTEST"):
        try:
            days = 30 if "1 THANG" in text or "1 THÁNG" in text else 7
            clean_text = text.replace("BACKTEST", "").replace("1 THANG", "").replace("1 THÁNG", "").replace("VON", "")
            match = re.search(r'\b[A-Z0-9]+\b', clean_text)
            if not match: return
            symbol = match.group(0)
            
            cap = 500000 if user['currency'] == 'VNDC' else 100
            if "VON" in text:
                nums = re.findall(r'\d+', text.split("VON")[1])
                if nums: cap = float(''.join(nums))
                
            bot.reply_to(message, f"⏳ Đang Backtest SMC cho {symbol}...")
            threading.Thread(target=process_backtest, args=(chat_id, symbol, cap, days)).start()
        except: pass
        return

    if text.startswith("ENTRY NOW"):
        symbol = text.replace("ENTRY NOW", "").replace("(", "").replace(")", "").strip()
        if not check_all_in_safety(user, message, [symbol]): return
        opens, highs, lows, closes, vols, _ = lay_data_binance(symbol)
        if closes is None: return
        tin_hieu, sl, tp, ly_do = check_smc_setup(opens, highs, lows, closes, vols, -1)
        # Entry thủ công (nếu không có tín hiệu SMC thì đánh đại theo giá hiện tại)
        if not tin_hieu:
            p_now = closes[-1]
            tin_hieu, sl, tp = "LONG 🟢", p_now*0.9995, p_now*1.001
            ly_do = "Lệnh tay khẩn cấp"
        execute_trade(chat_id, symbol, tin_hieu, ly_do, closes[-1], sl, tp)
        
        if not user.get('is_monitoring', False):
            user['is_monitoring'] = True
            threading.Thread(target=monitor_thread, args=(chat_id,), daemon=True).start()
        return

    if text == "SCAN":
        res = scan_market(chat_id)
        if res: bot.reply_to(message, "🔍 **KÈO SMC M5/M15:**\n" + "\n".join(res))
        else: bot.reply_to(message, "Thị trường xấu, chưa có kèo.")
        return
    
    if text.startswith("THEO DOI"):
        coins = text.replace("THEO DOI", "").replace(",", " ").split()
        valid = [c.strip().upper() for c in coins if c.strip()][:5]
        if valid:
            if not check_all_in_safety(user, message, valid): return
            user['watching'] = valid
            for coin in valid:
                if coin in user['auto_watching']: user['auto_watching'].remove(coin)
            bot.reply_to(message, f"📡 Đang rình SMC: {', '.join(valid)}")
            if not user.get('is_monitoring', False):
                user['is_monitoring'] = True
                threading.Thread(target=monitor_thread, args=(chat_id,), daemon=True).start()
        return
    
    if text.startswith("AUTO "):
        coins = text.replace("AUTO", "").strip().upper().replace(",", " ").split()
        if not coins: return
        if not check_all_in_safety(user, message, coins): return
        
        added = []
        for c in coins:
            if c not in user['auto_watching']:
                user['auto_watching'].append(c)
                added.append(c)
                if c in user['watching']: user['watching'].remove(c)

        if added:
            bot.reply_to(message, f"🔄 Đã bật **AUTO SMC 24/7**: {', '.join(added)}")
            if not user.get('is_monitoring', False):
                user['is_monitoring'] = True
                threading.Thread(target=monitor_thread, args=(chat_id,), daemon=True).start()
        return

    if text == "DUNG":
        user['watching'] = []
        user['auto_watching'] = [] 
        user['is_monitoring'] = False
        bot.reply_to(message, "🛑 Đã hủy mọi chế độ Auto/Theo dõi.")
        return
    
    if text in ["THONG KE", "THỐNG KÊ"]:
        w, l = user['stats']['wins'], user['stats']['losses']
        rate = w/(w+l)*100 if (w+l)>0 else 0
        bot.reply_to(message, f"📊 Win: {w} | Loss: {l} ({rate:.1f}%)")
        return
    
    if text in ["RESET THONG KE", "RESET THỐNG KÊ"]:
        user['stats'] = {'wins': 0, 'losses': 0}
        bot.reply_to(message, "♻️ Đã làm sạch thống kê.")
        return

    if text in ["XEM THEO DOI", "LIST"]:
        msg = ""
        if user['watching']: msg += f"📋 Rình (1 lần): {', '.join(user['watching'])}\n"
        if user['auto_watching']: msg += f"🔄 Auto SMC: {', '.join(user['auto_watching'])}"
        if not msg: msg = "📭 Trống."
        bot.reply_to(message, msg)
        return

    symbol = text.split()[0]
    msg = bot.reply_to(message, f"🔍 Phân tích SMC {symbol}...")
    ty = lay_ty_gia_remitano()
    if ty: TY_GIA_USDT_CACHE = ty
    
    opens, highs, lows, closes, vols, src = lay_data_binance(symbol)
    if closes is not None:
        photo = ve_chart(symbol, opens, highs, lows, closes, vols)
        tin_hieu, _, _, ly_do = check_smc_setup(opens, highs, lows, closes, vols, -1)
        status = f"🚀 **{tin_hieu}**" if tin_hieu else "Giá đang chạy, chưa có Setup."
        if ly_do: status += f"\n({ly_do})"
        gia_vnd = closes[-1] * TY_GIA_USDT_CACHE
        caption = f"📊 **{symbol} (M5/M15 SMC)**\n🇺🇸 ${closes[-1]:,.4f}\n🇻🇳 {gia_vnd:,.0f} đ\nStatus: {status}\n📡 {src}"
        bot.send_photo(chat_id, photo, caption=caption, parse_mode="Markdown")
        bot.delete_message(chat_id, msg.message_id)
    else:
        gia, src, sym = lay_gia_coingecko_smart(symbol)
        if gia:
             gia_vnd = gia * TY_GIA_USDT_CACHE
             bot.edit_message_text(f"💰 {sym}: ${gia:,.6f} (≈ {gia_vnd:,.0f} đ)\n📡 {src}", chat_id, msg.message_id)
        else:
             bot.edit_message_text("❌ Không tìm thấy coin.", chat_id, msg.message_id)

print("🤖 BOT SMC ICT ĐANG CHẠY (M5/M15 MULTI-TIMEFRAME)...")
keep_alive()
bot.infinity_polling()

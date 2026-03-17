import telebot
import requests
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
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
            'bet_amount': 50000,  
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

# --- LẤY DATA BINANCE FUTURES ---
def lay_data_binance(symbol, limit=500):
    NODES = [
        "https://fapi.binance.com/fapi/v1/klines", 
        "https://api.binance.com/api/v3/klines", 
        "https://api1.binance.com/api/v3/klines"
    ]
    pair = symbol.upper() + "USDT"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    for url_base in NODES:
        try:
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

def lay_gia_coingecko_smart(symbol):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        search_url = f"https://api.coingecko.com/api/v3/search?query={symbol}"
        res = requests.get(search_url, headers=headers, timeout=5).json()
        if 'coins' in res and len(res['coins']) > 0:
            coin = res['coins'][0]
            coin_id = coin['id']
            sym = coin['symbol'].upper()
            price_url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
            pres = requests.get(price_url, headers=headers, timeout=5).json()
            if coin_id in pres: return pres[coin_id]['usd'], "CoinGecko", sym
    except: pass
    return None, None, None

# --- SMC TRADINGVIEW (LUDOGH68) TO PYTHON LOGIC ---
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
    if i == -1: i = len(closes) - 1
    if i < 100: return None, 0, 0, ""

    start_idx = max(0, i - 300) 
    
    c_h = highs[start_idx:i+1]
    c_l = lows[start_idx:i+1]
    c_c = closes[start_idx:i+1]

    # Xác định Cấu trúc (Structure Direction) = Swing Lookback 10
    sw_h, sw_l = find_swing_points(c_h, c_l, 10)
    if len(sw_h) < 2 or len(sw_l) < 2:
        return None, 0, 0, ""

    # Uptrend = Đáy sau cao hơn đáy trước & Đỉnh sau cao hơn đỉnh trước
    uptrend = (sw_h[-1][1] > sw_h[-2][1]) and (sw_l[-1][1] > sw_l[-2][1])
    downtrend = (sw_h[-1][1] < sw_h[-2][1]) and (sw_l[-1][1] < sw_l[-2][1])

    # Quét tìm FVG (Fair Value Gap) theo chuẩn PineScript
    bullish_fvgs = []
    bearish_fvgs = []
    
    # Lấy 50 nến gần nhất để quét FVG (tránh tìm xa quá)
    fvg_start = max(0, len(c_h) - 50)
    for j in range(fvg_start, len(c_h) - 2):
        # Bullish FVG: low[j+2] > high[j] (Gap hở giữa 3 cây nến)
        if c_l[j+2] > c_h[j]:
            bot = c_h[j]
            top = c_l[j+2]
            # Mitigated (Đã bị lấp) nếu có râu nến nào đâm thủng mép dưới FVG
            mitigated = any(c_l[k] <= bot for k in range(j+3, len(c_h)))
            if not mitigated:
                bullish_fvgs.append((bot, top))
                
        # Bearish FVG: high[j+2] < low[j]
        if c_h[j+2] < c_l[j]:
            bot = c_h[j+2]
            top = c_l[j]
            # Mitigated nếu có râu đâm thủng mép trên FVG
            mitigated = any(c_h[k] >= top for k in range(j+3, len(c_h)))
            if not mitigated:
                bearish_fvgs.append((bot, top))

    curr_h, curr_l, curr_c = c_h[-1], c_l[-1], c_c[-1]
    tin_hieu, sl, tp, ly_do = None, 0, 0, ""

    # --- KHỚP LỆNH SMC BOT ---
    if uptrend:
        for bot_fvg, top_fvg in bullish_fvgs:
            # Giá chạm vào vùng Bullish FVG nhưng chưa thủng đáy (Đóng cửa trên)
            if curr_l <= top_fvg and curr_c > bot_fvg:
                tin_hieu = "LONG (SMC) 🟢"
                ly_do = "M5 Uptrend + Retest Bullish FVG"
                sl = bot_fvg * 0.9995 # Cắt lỗ ngay dưới mép hộp FVG
                tp = curr_c + (curr_c - sl) * 2.0 # Tự động R:R 1:2
                break 

    elif downtrend:
        for bot_fvg, top_fvg in bearish_fvgs:
            # Giá chạm Bearish FVG nhưng rút râu xuống
            if curr_h >= bot_fvg and curr_c < top_fvg:
                tin_hieu = "SHORT (SMC) 🔴"
                ly_do = "M5 Downtrend + Retest Bearish FVG"
                sl = top_fvg * 1.0005 # Cắt lỗ trên mép hộp FVG
                tp = curr_c - (sl - curr_c) * 2.0
                break

    return tin_hieu, sl, tp, ly_do

# --- BACKTEST (SIÊU TỐC ĐÃ FIX) ---
def process_backtest(chat_id, symbol, start_capital, days):
    user = get_user_data(chat_id)
    try:
        opens, highs, lows, closes, vols, count = lay_data_lich_su(symbol, days=days)
        if closes is None or len(closes) < 150:
            bot.send_message(chat_id, f"❌ Lỗi mạng hoặc không đủ dữ liệu nến M5 để test.")
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
                    'amount': margin_needed 
                }

        total_trades = wins + losses
        win_rate = (wins/total_trades * 100) if total_trades > 0 else 0
        pnl_total = balance - start_capital
        emoji = "🚀 TO THE MOON" if pnl_total >= 0 else "🩸 ĐỔ MÁU"
        if balance < (start_capital * 0.05): emoji = "💀 CHÁY TÀI KHOẢN"
        pnl_sign = "+" if pnl_total >= 0 else ""

        msg = (
            f"📊 **BÁO CÁO BACKTEST SMC ICT (Bản Mới)** 📊\n"
            f"🪙 **Coin:** {symbol} (Khung M5)\n"
            f"🗓 **Thời gian:** {days} Ngày ({count} nến)\n"
            f"⚙️ **Đòn bẩy:** x{leverage} | **Risk:** 1%\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💵 **Vốn ban đầu:** {fmt_money(start_capital, user['currency'])}\n"
            f"🏁 **Vốn hiện tại:** {fmt_money(balance, user['currency'])}\n"
            f"📈 **Lợi nhuận (P&L):** {pnl_sign}{fmt_money(pnl_total, user['currency'])} {emoji}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏆 **Thắng:** {wins} lệnh\n"
            f"🥀 **Thua:** {losses} lệnh\n"
            f"🔄 **Tổng giao dịch:** {total_trades} lệnh\n"
            f"🎯 **Tỷ lệ Win (Winrate):** {win_rate:.1f}%\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 *Thuật toán: Pine Script SMC (FVG + Cấu trúc Swing).* "
        )
        bot.send_message(chat_id, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Lỗi Backtest: Vui lòng thử lại!")

# --- VẼ CHART NẾN NHẬT KÈM HỘP FVG ---
def ve_chart(symbol, opens, highs, lows, closes, vols):
    view = 60 
    p_o = opens[-view:]
    p_h = highs[-view:]
    p_l = lows[-view:]
    p_c = closes[-view:]
    
    fig, ax1 = plt.subplots(1, 1, figsize=(10, 6))
    fig.tight_layout(pad=3.0)

    # 1. Vẽ nến Candlestick
    x = np.arange(view)
    up = p_c >= p_o
    down = p_c < p_o
    
    ax1.vlines(x[up], p_l[up], p_h[up], color='#26a69a', linewidth=1)
    ax1.vlines(x[down], p_l[down], p_h[down], color='#ef5350', linewidth=1)
    width = 0.6
    ax1.bar(x[up], p_c[up] - p_o[up], width, bottom=p_o[up], color='#26a69a', edgecolor='#26a69a')
    ax1.bar(x[down], p_o[down] - p_c[down], width, bottom=p_c[down], color='#ef5350', edgecolor='#ef5350')

    # 2. Tự động Quét và Vẽ Hộp FVG chuẩn TradingView
    for i in range(view - 2):
        # Bullish FVG
        if p_l[i+2] > p_h[i]:
            bot_fvg = p_h[i]
            top_fvg = p_l[i+2]
            # Kéo hộp FVG tới hiện tại
            is_mitigated = any(p_l[k] <= bot_fvg for k in range(i+3, view))
            # Hộp màu xanh đậm nếu nguyên vẹn, màu xám nếu đã bị lấp
            bg_color = 'gray' if is_mitigated else '#26a69a'
            alpha_val = 0.15 if is_mitigated else 0.4
            
            rect = patches.Rectangle((i+1, bot_fvg), view - i, top_fvg - bot_fvg, linewidth=0, edgecolor='none', facecolor=bg_color, alpha=alpha_val)
            ax1.add_patch(rect)
            
        # Bearish FVG
        if p_h[i+2] < p_l[i]:
            bot_fvg = p_h[i+2]
            top_fvg = p_l[i]
            is_mitigated = any(p_h[k] >= top_fvg for k in range(i+3, view))
            bg_color = 'gray' if is_mitigated else '#ef5350'
            alpha_val = 0.15 if is_mitigated else 0.4
            
            rect = patches.Rectangle((i+1, bot_fvg), view - i, top_fvg - bot_fvg, linewidth=0, edgecolor='none', facecolor=bg_color, alpha=alpha_val)
            ax1.add_patch(rect)

    ax1.set_title(f'{symbol} (M5) SMC FVG Engine')
    ax1.grid(True, alpha=0.2)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

# --- EXECUTE ---
def scan_market(chat_id):
    bot.send_message(chat_id, "📡 **Đang quét SMC (FVG Box)...**", parse_mode="Markdown")
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
    
    risk_amount = user['balance'] * 0.01 
    dist_pct = abs(entry - sl) / entry
    if dist_pct == 0: dist_pct = 0.001
    
    pos_size = risk_amount / dist_pct
    margin_needed = pos_size / 30 
    
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
        f"🚀 **ENTRY SMC MỚI: {symbol}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🧭 **Loại Lệnh:** {tin_hieu}\n"
        f"💡 **Lý do:** {ly_do}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 **Entry:** ${entry:,.4f}\n"
        f"💸 **Ký quỹ:** {fmt_money(margin_needed, user['currency'])}{note}\n"
        f"🛑 **Stoploss (SL):** ${sl:,.4f}\n"
        f"🎯 **Takeprofit (TP):** ${tp:,.4f}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 **Số dư ví:** {fmt_money(user['balance'], user['currency'])}"
    )
    bot.send_message(chat_id, msg, parse_mode="Markdown")

# --- MONITOR 24/7 ---
def monitor_thread(chat_id):
    bot.send_message(chat_id, "🤖 Bot SMC (TradingView logic) đã sẵn sàng săn mồi 24/7...")
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
                            auto_msg = "\n🔄 *Tiếp tục rình mồi SMC...*" if is_auto_trade else "\n🏁 *Đã dừng theo dõi.*"
                            pnl_sign = "+" if pnl >= 0 else ""
                            
                            msg_to_send = (
                                f"🔔 **CHỐT LỆNH SMC {symbol} | {ket_qua}**\n"
                                f"━━━━━━━━━━━━━━━━━━\n"
                                f"📈 **Lợi nhuận:** {pnl_sign}{fmt_money(pnl, user['currency'])}\n"
                                f"💰 **Vốn mới:** {fmt_money(user['balance'], user['currency'])}\n"
                                f"{auto_msg}"
                            )
                            
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

# --- BOT COMMANDS (GIAO DIỆN HELP FULL XỊN XÒ) ---
@bot.message_handler(commands=['start', 'help'])
def send_help(message):
    user = get_user_data(message.chat.id)
    help_text = (
        "📖 **HƯỚNG DẪN BOT SMC (PINE SCRIPT)** 📖\n\n"
        "🛠 **1. CÀI ĐẶT VỐN & ĐA VÍ:**\n"
        "   👉 `/Von VNDC 1000000`: Set vốn bằng VNĐ.\n"
        "   👉 `/Von USDT 50`: Set vốn bằng USD.\n"
        "   👉 `/Chuyen USDT` (hoặc VNDC): Tự động quy đổi số dư sang ví mới.\n"
        "   👉 `/Cuoc 50000`: Cài tiền đi từng lệnh.\n"
        "   👉 `/Cuoc all`: Đánh 100% vốn.\n"
        "   ℹ️ *Mặc định Bot tự động tính vol lệnh Risk 1% tài khoản chuẩn Quỹ.*\n\n"
        "🧪 **2. BACKTEST SMC (SIÊU TỐC):**\n"
        "   👉 `Backtest [Coin] Von [Tiền]`: Test 7 ngày.\n"
        "      - VD: `Backtest BTC Von 500000`\n"
        "   👉 `Backtest 1 thang [Coin] Von [Tiền]`: Test 30 ngày.\n"
        "      - VD: `Backtest 1 thang BTC Von 500000`\n\n"
        "🚀 **3. SĂN KÈO SMC (M5 SWEEP + FVG):**\n"
        "   👉 `Entry now [Coin]`: Vào lệnh tay NGAY LẬP TỨC.\n"
        "   👉 `Scan`: Quét 10 coin có tín hiệu FVG/Liquidity.\n"
        "   👉 `Theo doi [Coin]`: Canh tín hiệu -> Vào lệnh -> Xong thì Dừng.\n"
        "   👉 `/Auto [Coin]`: Canh tín hiệu -> Vào lệnh -> Xong thì Lặp lại 24/7.\n\n"
        "📊 **4. TIỆN ÍCH KHÁC:**\n"
        "   👉 `Thong ke`: Xem tỷ lệ thắng/thua.\n"
        "   👉 `Reset thong ke`: Xóa sạch lịch sử Win/Loss.\n"
        "   👉 `Xem theo doi`: Xem danh sách đang canh.\n"
        "   👉 `Dung`: Dừng tất cả (Cả Auto và Theo dõi).\n"
        "   👉 Nhập tên Coin bất kỳ (VD: `PEPE`) để xem Chart M5 Candlestick + FVG.\n\n"
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
                try:
                    val = float(parts[1].replace(',', ''))
                    user['is_all_in'] = False
                    user['bet_amount'] = val
                    bot.reply_to(message, f"✅ Đã tắt ALL-IN và set cược cố định: **{fmt_money(val, user['currency'])}**", parse_mode="Markdown")
                except: pass
        return

    if text in ["XEM VON", "VỐN"]:
        bot.reply_to(message, f"💳 Ví: **{user['currency']}**\n💰 Vốn: **{fmt_money(user['balance'], user['currency'])}**\n💵 Chế độ cược: **{'ALL-IN' if user['is_all_in'] else 'Risk 1% SMC'}**", parse_mode="Markdown")
        return

    if text.startswith("BACKTEST"):
        try:
            days = 30 if ("1 THANG" in text or "1 THÁNG" in text) else 7
            clean_text = text.replace("BACKTEST", "").replace("1 THANG", "").replace("1 THÁNG", "").strip()
            parts = clean_text.split("VON")
            coin_part = parts[0].strip()
            
            symbol = ""
            for word in coin_part.split():
                if word in WATCHLIST_MARKET:
                    symbol = word
                    break
            
            if not symbol:
                match = re.search(r'\b([A-Z]{3,})\b', coin_part)
                if match: symbol = match.group(1)
                else: 
                    bot.reply_to(message, "⚠️ Nhập sai cú pháp. VD: `Backtest 1 thang BTC Von 500000`")
                    return
            
            cap = 500000 if user['currency'] == 'VNDC' else 100
            if len(parts) > 1:
                nums = re.findall(r'\d+', parts[1])
                if nums: cap = float(''.join(nums))
                
            bot.reply_to(message, f"⏳ **Đang Backtest SMC (Tốc độ Cao)...**\n🪙 Coin: **{symbol}**\n🗓 Khung thời gian: **{'30 Ngày' if days==30 else '7 Ngày'}**\n💰 Vốn giả định: **{fmt_money(cap, user['currency'])}**\n⚡️ *Bot đang tính toán FVG của ngàn nến M5...*")
            threading.Thread(target=process_backtest, args=(chat_id, symbol, cap, days)).start()
        except Exception as e:
            bot.reply_to(message, f"⚠️ Lỗi cú pháp Backtest!")
        return

    if text.startswith("ENTRY NOW"):
        symbol = text.replace("ENTRY NOW", "").replace("(", "").replace(")", "").strip()
        if not check_all_in_safety(user, message, [symbol]): return
        opens, highs, lows, closes, vols, _ = lay_data_binance(symbol)
        if closes is None: return
        tin_hieu, sl, tp, ly_do = check_smc_setup(opens, highs, lows, closes, vols, -1)
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
    msg = bot.reply_to(message, f"🔍 Phân tích FVG Box {symbol}...")
    ty = lay_ty_gia_remitano()
    if ty: TY_GIA_USDT_CACHE = ty
    
    opens, highs, lows, closes, vols, src = lay_data_binance(symbol)
    if closes is not None:
        photo = ve_chart(symbol, opens, highs, lows, closes, vols)
        tin_hieu, _, _, ly_do = check_smc_setup(opens, highs, lows, closes, vols, -1)
        status = f"🚀 **{tin_hieu}**" if tin_hieu else "Giá đang chạy, chưa có Setup."
        if ly_do: status += f"\n({ly_do})"
        gia_vnd = closes[-1] * TY_GIA_USDT_CACHE
        caption = f"📊 **{symbol} (SMC Chart)**\n🇺🇸 ${closes[-1]:,.4f}\n🇻🇳 {gia_vnd:,.0f} đ\nStatus: {status}\n📡 {src}"
        bot.send_photo(chat_id, photo, caption=caption, parse_mode="Markdown")
        bot.delete_message(chat_id, msg.message_id)
    else:
        gia, src, sym = lay_gia_coingecko_smart(symbol)
        if gia:
             gia_vnd = gia * TY_GIA_USDT_CACHE
             bot.edit_message_text(f"💰 {sym}: ${gia:,.6f} (≈ {gia_vnd:,.0f} đ)\n📡 {src}", chat_id, msg.message_id)
        else:
             bot.edit_message_text("❌ Không tìm thấy coin.", chat_id, msg.message_id)

print("🤖 BOT TRADINGVIEW ĐANG CHẠY (BẢN VẼ HỘP FVG & NẾN NHẬT)...")
keep_alive()
bot.infinity_polling()

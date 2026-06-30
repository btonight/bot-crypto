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

def get_user_data(chat_id):
    if chat_id not in USER_DATA:
        USER_DATA[chat_id] = {
            'balance': 500.0,      # Mặc định vốn USDT
            'bet_amount': 50.0,    # Mặc định cược USDT
            'risk_percent': 1.0,   # Mặc định rủi ro 1%
            'is_all_in': False,   
            'currency': 'USDT',    # Chỉ còn USDT
            'watching': [],       
            'auto_watching': [],  
            'active_trades': {},
            'stats': {'wins': 0, 'losses': 0},
            'is_monitoring': False,
            'cooldowns': {} 
        }
    return USER_DATA[chat_id]

def fmt_money(amount, currency):
    """Định dạng tiền tệ, chỉ hỗ trợ USDT"""
    if currency == 'USDT':
        return f"${amount:,.2f}"
    return f"{amount:,.2f}"  # Fallback, nhưng không nên dùng

# --- HÀM GỬI TIN NHẮN CHỐNG MẤT KẾT NỐI ---
def send_alert(chat_id, msg_text):
    """Gửi tin nhắn với retry logic (giữ nguyên)"""
    for _ in range(3): # Thử lại 3 lần nếu mạng lỗi
        try:
            bot.send_message(chat_id, msg_text, parse_mode="Markdown")
            return True
        except Exception:
            time.sleep(1)
    # Nếu Markdown bị lỗi, thử gửi dạng text thường
    try:
        bot.send_message(chat_id, msg_text.replace('*', ''))
        return True
    except:
        return False

# --- LẤY DATA BINANCE FUTURES ---
def lay_data_binance(symbol, limit=500):
    """Lấy dữ liệu nến từ Binance Futures (giữ nguyên)"""
    NODES = ["https://fapi.binance.com/fapi/v1/klines", "https://api.binance.com/api/v3/klines", "https://api1.binance.com/api/v3/klines"]
    pair = symbol.upper() + "USDT"
    headers = {'User-Agent': 'Mozilla/5.0'}
    for url_base in NODES:
        try:
            data = requests.get(f"{url_base}?symbol={pair}&interval=5m&limit={limit}", headers=headers, timeout=5).json()
            if isinstance(data, list) and len(data) > 0:
                o = np.array([float(x[1]) for x in data])
                h = np.array([float(x[2]) for x in data])
                l = np.array([float(x[3]) for x in data])
                c = np.array([float(x[4]) for x in data])
                return o, h, l, c, "Futures ⚡" if "fapi" in url_base else "Spot"
        except: continue
    return None, None, None, None, None

def lay_data_lich_su(symbol, days=7):
    """Lấy dữ liệu lịch sử cho backtest (giữ nguyên)"""
    try:
        pair = symbol.upper() + "USDT"
        rounds = int((days * 288) / 1000) + 2
        all_o, all_h, all_l, all_c = [], [], [], []
        end_time = int(time.time() * 1000) 
        headers = {'User-Agent': 'Mozilla/5.0'}
        for _ in range(rounds):
            data = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={pair}&interval=5m&limit=1000&endTime={end_time}", headers=headers, timeout=5).json()
            if not data: break
            all_o = [float(x[1]) for x in data] + all_o
            all_h = [float(x[2]) for x in data] + all_h
            all_l = [float(x[3]) for x in data] + all_l
            all_c = [float(x[4]) for x in data] + all_c
            end_time = data[0][0] - 1
        return np.array(all_o), np.array(all_h), np.array(all_l), np.array(all_c), len(all_c)
    except: pass
    return None, None, None, None, 0

def lay_gia_coingecko_smart(symbol):
    """Lấy giá hiện tại từ CoinGecko (giữ nguyên, chỉ trả về USD)"""
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

# --- ENGINE SMC THEO CHUẨN PINE SCRIPT (LUDOGH68) ---
def run_smc_engine(opens, highs, lows, closes):
    """Engine phân tích SMC (giữ nguyên hoàn toàn)"""
    fvgs = [] 
    lines = [] 
    
    struct_high = highs[0]
    struct_low = lows[0]
    struct_h_idx = 0
    struct_l_idx = 0
    direction = 0 
    
    signal, sl, tp, reason = None, 0, 0, ""

    for i in range(10, len(closes)):
        # 1. Tạo FVG
        if highs[i-2] < lows[i]:
            fvgs.append({'type': 'bull', 'top': lows[i], 'bot': highs[i-2], 'start': i-1, 'mitigated': False, 'deleted': False})
        if lows[i-2] > highs[i]:
            fvgs.append({'type': 'bear', 'top': lows[i-2], 'bot': highs[i], 'start': i-1, 'mitigated': False, 'deleted': False})

        # 2. Xử lý FVG (Mitigated - Xám / Deleted - Xóa hẳn)
        for f in fvgs:
            if f['deleted']: continue
            if f['type'] == 'bull':
                if lows[i] <= f['bot']: f['deleted'] = True 
                elif lows[i] < f['top']: f['mitigated'] = True 
            elif f['type'] == 'bear':
                if highs[i] >= f['top']: f['deleted'] = True
                elif highs[i] > f['bot']: f['mitigated'] = True

        fvgs = [f for f in fvgs if not f['deleted']]

        # 3. Cấu trúc (BOS / CHOCH)
        curr_c = closes[i]
        if curr_c < struct_low:
            line_type = "BOS" if direction == 1 else "CHoCH"
            lines.append({'type': line_type, 'dir': 'bear', 'price': struct_low, 'start': struct_l_idx, 'end': i})
            direction = 1
            struct_h_idx = i - 10 + np.argmax(highs[i-10:i+1])
            struct_high = highs[struct_h_idx]
            struct_low = lows[i]
            struct_l_idx = i

        elif curr_c > struct_high:
            line_type = "BOS" if direction == 2 else "CHoCH"
            lines.append({'type': line_type, 'dir': 'bull', 'price': struct_high, 'start': struct_h_idx, 'end': i})
            direction = 2
            struct_l_idx = i - 10 + np.argmin(lows[i-10:i+1])
            struct_low = lows[struct_l_idx]
            struct_high = highs[i]
            struct_h_idx = i

        else:
            if highs[i] > struct_high and (direction == 0 or direction == 2):
                struct_high = highs[i]
                struct_h_idx = i
            elif lows[i] < struct_low and (direction == 0 or direction == 1):
                struct_low = lows[i]
                struct_l_idx = i

        # 4. KÍCH HOẠT LỆNH TRÊN CÂY NẾN CUỐI CÙNG (Đã đóng cửa)
        if i == len(closes) - 1:
            for f in reversed(fvgs):
                if not f['mitigated']:
                    if direction == 2 and f['type'] == 'bull' and lows[i] <= f['top'] and closes[i] > f['bot']:
                        signal = "LONG 🟢"
                        reason = "Uptrend (BOS/CHoCH) + Retest FVG"
                        sl = f['bot'] * 0.9995
                        tp = closes[i] + (closes[i] - sl) * 2.0
                        break
                    elif direction == 1 and f['type'] == 'bear' and highs[i] >= f['bot'] and closes[i] < f['top']:
                        signal = "SHORT 🔴"
                        reason = "Downtrend (BOS/CHoCH) + Retest FVG"
                        sl = f['top'] * 1.0005
                        tp = closes[i] - (sl - closes[i]) * 2.0
                        break

    return signal, sl, tp, reason, fvgs, lines, struct_high, struct_low, struct_h_idx, struct_l_idx

# --- VẼ CHART SMC CHUẨN TRADINGVIEW ---
def ve_chart_smc(symbol, opens, highs, lows, closes, fvgs, lines, struct_high, struct_low, struct_h_idx, struct_l_idx, active_trade=None):
    """Vẽ chart SMC với matplotlib (giữ nguyên)"""
    view = 100 
    start_idx = len(closes) - view
    
    p_o = opens[start_idx:]
    p_h = highs[start_idx:]
    p_l = lows[start_idx:]
    p_c = closes[start_idx:]
    
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor('#1e222d') 
    ax.set_facecolor('#1e222d')
    
    x = np.arange(view)
    up = p_c >= p_o
    down = p_c < p_o
    
    ax.vlines(x[up], p_l[up], p_h[up], color='#089981', linewidth=1)
    ax.vlines(x[down], p_l[down], p_h[down], color='#f23645', linewidth=1)
    ax.bar(x[up], p_c[up] - p_o[up], 0.6, bottom=p_o[up], color='#089981')
    ax.bar(x[down], p_o[down] - p_c[down], 0.6, bottom=p_c[down], color='#f23645')

    for f in fvgs[-15:]: 
        if f['start'] >= start_idx:
            x_start = f['start'] - start_idx
            width = view - x_start
            height = f['top'] - f['bot']
            
            if f['mitigated']:
                color = '#787b86'
                alpha = 0.15
            else:
                color = '#089981' if f['type'] == 'bull' else '#f23645'
                alpha = 0.25
                
            rect = patches.Rectangle((x_start, f['bot']), width, height, linewidth=1, edgecolor=color, facecolor=color, alpha=alpha)
            ax.add_patch(rect)
            if not f['mitigated']:
                ax.text(x_start + width/2, f['bot'] + height/2, 'FVG', color='white', fontsize=7, ha='center', va='center', alpha=0.7)

    for l in lines:
        if l['start'] >= start_idx or l['end'] >= start_idx:
            x1 = max(0, l['start'] - start_idx)
            x2 = min(view, l['end'] - start_idx)
            line_color = '#e0e3eb' if l['type'] == 'BOS' else '#ffeb3b'
            ax.plot([x1, x2], [l['price'], l['price']], color=line_color, linestyle='--', linewidth=1)
            ax.text((x1+x2)/2, l['price'], l['type'], color=line_color, fontsize=8, ha='center', va='bottom')

    x_start_h = max(0, struct_h_idx - start_idx)
    ax.plot([x_start_h, view], [struct_high, struct_high], color='#2962FF', linestyle='-', linewidth=1.2, alpha=0.7)
    x_start_l = max(0, struct_l_idx - start_idx)
    ax.plot([x_start_l, view], [struct_low, struct_low], color='#2962FF', linestyle='-', linewidth=1.2, alpha=0.7)

    if active_trade:
        ep = active_trade['entry']
        sl = active_trade['sl']
        tp = active_trade['tp']
        
        ax.axhline(ep, color='#e0e3eb', linestyle='-', linewidth=1.5)
        ax.axhline(sl, color='#f23645', linestyle='-', linewidth=1.5)
        ax.axhline(tp, color='#089981', linestyle='-', linewidth=1.5)
        
        ax.text(view - 2, ep, ' ENTRY', color='white', fontsize=9, ha='right', va='bottom', backgroundcolor='#787b86')
        ax.text(view - 2, sl, ' SL', color='white', fontsize=9, ha='right', va='bottom', backgroundcolor='#f23645')
        ax.text(view - 2, tp, ' TP', color='white', fontsize=9, ha='right', va='bottom', backgroundcolor='#089981')
        
        ax.axhspan(ep, tp, color='#089981', alpha=0.1)
        ax.axhspan(ep, sl, color='#f23645', alpha=0.1)

    ax.set_title(f'{symbol} (M5) SMC LudoGH68 Indicator', color='white')
    ax.grid(True, color='#2a2e39', linestyle='-', linewidth=0.5)
    ax.tick_params(colors='white')
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close()
    return buf

# --- BACKTEST ---
def process_backtest(chat_id, symbol, start_capital, days):
    """Hàm backtest (Đã tích hợp quản lý rủi ro động)"""
    user = get_user_data(chat_id)
    try:
        opens, highs, lows, closes, count = lay_data_lich_su(symbol, days=days)
        if closes is None or len(closes) < 150:
            bot.send_message(chat_id, f"❌ Lỗi mạng hoặc không đủ dữ liệu nến M5 để test.")
            return

        balance = start_capital
        wins, losses = 0, 0
        active_trade = None
        current_risk_percent = user.get('risk_percent', 1.0) # Lấy % rủi ro người dùng cài
        
        for i in range(150, len(closes)):
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
                    
                    # Dùng đòn bẩy tự động đã lưu trong lệnh
                    balance += move * active_trade['leverage'] * amt
                    if res == 'WIN': wins += 1
                    else: losses += 1
                    active_trade = None
                continue
            
            if balance <= (start_capital * 0.05): break 
            
            sig, sl, tp, _, _, _, _, _, _, _ = run_smc_engine(opens[i-150:i+1], highs[i-150:i+1], lows[i-150:i+1], closes[i-150:i+1])
            
            if sig:
                risk_amt = balance * (current_risk_percent / 100.0)
                entry = closes[i]
                dist_pct = abs(entry - sl) / entry
                if dist_pct == 0: dist_pct = 0.001
                
                # --- AUTO LEVERAGE CHO BACKTEST ---
                dynamic_leverage = int(1 / dist_pct)
                if dynamic_leverage < 1: dynamic_leverage = 1
                if dynamic_leverage > 125: dynamic_leverage = 125
                
                margin_needed = (risk_amt / dist_pct) / dynamic_leverage
                if margin_needed > balance: margin_needed = balance
                
                active_trade = {
                    'type': 'LONG' if 'LONG' in sig else 'SHORT',
                    'entry': entry, 'sl': sl, 'tp': tp, 
                    'amount': margin_needed,
                    'leverage': dynamic_leverage # Lưu đòn bẩy động
                }

        total_trades = wins + losses
        win_rate = (wins/total_trades * 100) if total_trades > 0 else 0
        pnl_total = balance - start_capital
        emoji = "🚀 TO THE MOON" if pnl_total >= 0 else "🩸 ĐỔ MÁU"
        if balance < (start_capital * 0.05): emoji = "💀 CHÁY TÀI KHOẢN"

        msg = (
            f"📊 **BÁO CÁO BACKTEST SMC PINESCRIPT** 📊\n"
            f"🪙 **Coin:** {symbol} (Khung M5)\n"
            f"🗓 **Thời gian:** {days} Ngày ({count} nến)\n"
            f"⚙️ **Đòn bẩy:** Auto | **Risk:** {current_risk_percent}%\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💵 **Vốn ban đầu:** {fmt_money(start_capital, 'USDT')}\n"
            f"🏁 **Vốn hiện tại:** {fmt_money(balance, 'USDT')}\n"
            f"📈 **Lợi nhuận (P&L):** {'+' if pnl_total >= 0 else ''}{fmt_money(pnl_total, 'USDT')} {emoji}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏆 **Thắng:** {wins} lệnh\n"
            f"🥀 **Thua:** {losses} lệnh\n"
            f"🔄 **Tổng giao dịch:** {total_trades} lệnh\n"
            f"🎯 **Tỷ lệ Win (Winrate):** {win_rate:.1f}%\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 *Thuật toán: Chờ Đóng Nến + Retest FVG.* "
        )
        send_alert(chat_id, msg)
    except Exception as e:
        send_alert(chat_id, f"❌ Lỗi Backtest: {e}")

# --- EXECUTE ---
def scan_market(chat_id):
    """Quét thị trường tìm tín hiệu (giữ nguyên)"""
    bot.send_message(chat_id, "📡 **Đang quét SMC (Chỉ lấy nến đã đóng)...**", parse_mode="Markdown")
    signals = []
    for symbol in WATCHLIST_MARKET:
        opens, highs, lows, closes, _ = lay_data_binance(symbol)
        if closes is not None:
            tin_hieu, _, _, _, _, _, _, _, _, _ = run_smc_engine(opens[:-1], highs[:-1], lows[:-1], closes[:-1])
            if tin_hieu:
                signals.append(f"🔥 {symbol}: {tin_hieu}")
    return signals[:10]

def execute_trade(chat_id, symbol, tin_hieu, ly_do, entry, sl, tp):
    """Thực hiện lệnh giao dịch (Đã cập nhật UI Rủi ro + Khoảng cách)"""
    user = get_user_data(chat_id)
    if user['balance'] <= 0:
        if not user.get('out_of_money_warned'):
            send_alert(chat_id, "❌ **Hết tiền Demo rồi! Vui lòng nạp thêm vốn bằng lệnh /Von**")
            user['out_of_money_warned'] = True
        return
    
    user['out_of_money_warned'] = False
    
    # --- BỘ NÃO QUẢN LÝ VỐN TỰ ĐỘNG ---
    current_risk_percent = user.get('risk_percent', 1.0)
    risk_factor = current_risk_percent / 100.0
    risk_amount = user['balance'] * risk_factor
    
    # Tính % khoảng cách SL
    dist_pct = abs(entry - sl) / entry
    if dist_pct == 0: dist_pct = 0.001
    dist_pct_display = dist_pct * 100  # Chuyển ra % để hiển thị
    
    # Tự động tính Đòn bẩy tối đa
    dynamic_leverage = int(1 / dist_pct)
    if dynamic_leverage < 1: dynamic_leverage = 1
    if dynamic_leverage > 125: dynamic_leverage = 125
    
    # Tính Số tiền Ký quỹ (Margin)
    margin_needed = (risk_amount / dist_pct) / dynamic_leverage 
    note = f" (Risk {current_risk_percent}% - Auto Margin)"
    
    # Xử lý trường hợp All-in
    if user.get('is_all_in', False):
        margin_needed = user['balance']
        note = " (ALL-IN CHÁY MÁY 🔥)"

    if margin_needed > user['balance']: 
        margin_needed = user['balance']
    # --- KẾT THÚC BỘ NÃO ---
    
    msg = (
        f"🚀 **ENTRY SMC MỚI: {symbol}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🧭 **Loại Lệnh:** {tin_hieu}\n"
        f"💡 **Lý do:** {ly_do}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 **Entry:** ${entry:,.4f}\n"
        f"💸 **Ký quỹ:** {fmt_money(margin_needed, 'USDT')}{note}\n"
        f"⚡ **Đòn bẩy:** x{dynamic_leverage} (Tự động)\n"
        f"🛑 **Stoploss (SL):** ${sl:,.4f} ({dist_pct_display:.2f}%)\n"
        f"🎯 **Takeprofit (TP):** ${tp:,.4f}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 **Số dư ví:** {fmt_money(user['balance'] - margin_needed, 'USDT')}"
    )
    
    # CHỈ KHI GỬI TIN NHẮN THÀNH CÔNG MỚI ĐƯỢC GHI LẠI LỆNH
    if send_alert(chat_id, msg):
        user['balance'] -= margin_needed
        user['active_trades'][symbol] = {
            'type': 'LONG' if 'LONG' in tin_hieu else 'SHORT',
            'entry': entry, 'sl': sl, 'tp': tp, 
            'amount': margin_needed, 
            'leverage': dynamic_leverage 
        }

# --- LUỒNG GIÁM SÁT GLOBAL ---
def global_monitor_thread():
    """Luồng giám sát toàn cục (giữ nguyên)"""
    print("🤖 Luồng giám sát Global đã khởi động (Chờ đóng nến)!")
    while True:
        try: 
            for chat_id in list(USER_DATA.keys()):
                user = USER_DATA[chat_id]
                if not user['watching'] and not user['active_trades'] and not user['auto_watching']: 
                    continue

                for symbol in list(user['watching']):
                    try: 
                        if symbol in user.get('cooldowns', {}) and time.time() < user['cooldowns'][symbol]: continue
                        opens, highs, lows, closes, _ = lay_data_binance(symbol)
                        if closes is not None:
                            tin_hieu, sl, tp, ly_do, _, _, _, _, _, _ = run_smc_engine(opens[:-1], highs[:-1], lows[:-1], closes[:-1])
                            if tin_hieu and symbol not in user['active_trades']:
                                execute_trade(chat_id, symbol, tin_hieu, ly_do, closes[-1], sl, tp) 
                                if symbol in user['watching']: user['watching'].remove(symbol)
                    except: pass

                for symbol in list(user['auto_watching']):
                    try: 
                        if symbol in user.get('cooldowns', {}) and time.time() < user['cooldowns'][symbol]: continue
                        if symbol in user['active_trades']: continue 

                        opens, highs, lows, closes, _ = lay_data_binance(symbol)
                        if closes is not None:
                            tin_hieu, sl, tp, ly_do, _, _, _, _, _, _ = run_smc_engine(opens[:-1], highs[:-1], lows[:-1], closes[:-1])
                            if tin_hieu:
                                execute_trade(chat_id, symbol, tin_hieu, ly_do, closes[-1], sl, tp)
                    except: pass
                
                for symbol in list(user['active_trades'].keys()):
                    try:
                        trade = user['active_trades'][symbol]
                        _, highs, lows, closes, _ = lay_data_binance(symbol)
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
                                move = (close_price - trade['entry']) / trade['entry'] if trade['type'] == 'LONG' else (trade['entry'] - close_price) / trade['entry']
                                pnl = move * trade['leverage'] * trade['amount']
                                
                                ket_qua = "WIN 🟢" if hit_tp else "LOSS 🔴"
                                is_auto_trade = (symbol in user['auto_watching'])
                                auto_msg = "\n🔄 *Tiếp tục rình mồi SMC...*" if is_auto_trade else "\n🏁 *Đã dừng theo dõi.*"
                                
                                msg_to_send = (
                                    f"🔔 **CHỐT LỆNH SMC {symbol} | {ket_qua}**\n"
                                    f"━━━━━━━━━━━━━━━━━━\n"
                                    f"📈 **Lợi nhuận:** {'+' if pnl >= 0 else ''}{fmt_money(pnl, 'USDT')}\n"
                                    f"💰 **Vốn mới:** {fmt_money(user['balance'] + trade['amount'] + pnl, 'USDT')}\n"
                                    f"{auto_msg}"
                                )
                                
                                send_alert(chat_id, msg_to_send)
                                user['balance'] += (trade['amount'] + pnl)
                                if hit_tp: user['stats']['wins'] += 1
                                else: user['stats']['losses'] += 1
                                del user['active_trades'][symbol]
                                user.setdefault('cooldowns', {})[symbol] = time.time() + 300 
                    except: pass
        except Exception:
            pass
        time.sleep(60) 

def check_all_in_safety(user, message, coins_to_add=[]):
    """Kiểm tra an toàn khi chế độ All-in (giữ nguyên)"""
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
    """Lệnh help (Đã update hướng dẫn Rui ro)"""
    user = get_user_data(message.chat.id)
    help_text = (
        "📖 **HƯỚNG DẪN BOT SMC (PINE SCRIPT)** 📖\n\n"
        "🛠 **1. CÀI ĐẶT VỐN & RỦI RO:**\n"
        "   👉 `/Von 500`: Set vốn 500 USDT.\n"
        "   👉 `/Ruiro 2`: Chỉnh mức rủi ro cắt lỗ (Ví dụ 2% tài khoản).\n"
        "   👉 `/Cuoc all`: Đánh 100% vốn.\n"
        "   ℹ️ *Mặc định Bot tự động tính vol lệnh Risk 1% tài khoản chuẩn Quỹ.*\n\n"
        "🧪 **2. BACKTEST SMC (SIÊU TỐC):**\n"
        "   👉 `Backtest [Coin] Von [Tiền]`: Test 7 ngày.\n"
        "      - VD: `Backtest BTC Von 100`\n"
        "   👉 `Backtest 1 thang [Coin] Von [Tiền]`: Test 30 ngày.\n"
        "      - VD: `Backtest 1 thang BTC Von 100`\n\n"
        "🚀 **3. SĂN KÈO SMC (M5 BOS + FVG - CHỜ ĐÓNG NẾN):**\n"
        "   👉 `Entry now [Coin]`: Vào lệnh tay NGAY LẬP TỨC.\n"
        "   👉 `Scan`: Quét 10 coin có tín hiệu FVG.\n"
        "   👉 `Theo doi [Coin]`: Canh tín hiệu -> Vào lệnh -> Xong thì Dừng.\n"
        "   👉 `/Auto [Coin]`: Canh tín hiệu -> Vào lệnh -> Xong thì Lặp lại 24/7.\n\n"
        "📊 **4. TIỆN ÍCH KHÁC:**\n"
        "   👉 `Thong ke`: Xem tỷ lệ thắng/thua.\n"
        "   👉 `Reset thong ke`: Xóa sạch lịch sử Win/Loss.\n"
        "   👉 `Xem theo doi`: Xem danh sách đang canh.\n"
        "   👉 `Dung`: Dừng tất cả (Cả Auto và Theo dõi).\n"
        "   👉 Nhập tên Coin bất kỳ (VD: `PEPE`) để xem Chart M5 SMC.\n\n"
        "--------------------------\n"
        f"💳 Ví: **USDT** (Đã loại bỏ VNDC)\n"
        f"💰 Vốn: **{fmt_money(user['balance'], 'USDT')}**\n"
        f"🛡 Rủi ro hiện tại: **{user.get('risk_percent', 1.0)}%**\n"
        f"💵 Chế độ cược: **{'ALL-IN (100%)' if user['is_all_in'] else 'Quản lý vốn Auto'}**"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['Auto', 'auto'])
def handle_auto(message):
    """Xử lý lệnh Auto (giữ nguyên)"""
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
    except Exception as e: bot.reply_to(message, f"Lỗi: {e}")

@bot.message_handler(func=lambda message: True)
def handle_msg(message):
    """Xử lý tin nhắn (Bổ sung lệnh Rủi ro)"""
    text = message.text.strip().upper()
    chat_id = message.chat.id
    user = get_user_data(chat_id)
    
    # --- CÀI ĐẶT RỦI RO ---
    if text.startswith("/RUIRO") or text.startswith("RUI RO") or text.startswith("RỦI RO"):
        nums = re.findall(r'[\d\.]+', text)
        if nums:
            try:
                val = float(nums[0])
                if val <= 0: val = 1.0
                user['risk_percent'] = val
                bot.reply_to(message, f"🛡 **Đã cập nhật mức Rủi ro:** {val}% / lệnh", parse_mode="Markdown")
            except: pass
        else:
            bot.reply_to(message, "⚠️ Cú pháp sai. Hãy gõ ví dụ: `/ruiro 2` hoặc `rui ro 1.5`")
        return

    # --- CÀI ĐẶT VỐN ---
    if text.startswith("VON ") or text.startswith("VỐN "):
        parts = text.split()
        if len(parts) == 2:
            try:
                val = float(parts[1].replace(',', ''))
                user['balance'] = val
                bot.reply_to(message, f"✅ Đã set vốn: **{fmt_money(val, 'USDT')}**", parse_mode="Markdown")
            except: pass
            return
        elif len(parts) >= 3 and parts[1] in ["USDT"]: 
            curr = parts[1]
            try:
                val = float(parts[2].replace(',', ''))
                user['currency'] = curr
                user['balance'] = val
                bot.reply_to(message, f"✅ Đã set lại ví: **{curr}**\n💰 Vốn: **{fmt_money(val, curr)}**", parse_mode="Markdown")
            except: pass
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
                    bot.reply_to(message, f"✅ Đã tắt ALL-IN. Vui lòng dùng lệnh `/ruiro` để quản lý vốn chuẩn hơn.", parse_mode="Markdown")
                except: pass
        return

    if text in ["XEM VON", "VỐN"]:
        bot.reply_to(message, f"💳 Ví: **USDT**\n💰 Vốn: **{fmt_money(user['balance'], 'USDT')}**\n🛡 Rủi ro cài đặt: **{user.get('risk_percent', 1.0)}%**\n💵 Chế độ cược: **{'ALL-IN' if user['is_all_in'] else 'Quản lý vốn Auto'}**", parse_mode="Markdown")
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
                else: return bot.reply_to(message, "⚠️ Nhập sai cú pháp. VD: `Backtest 1 thang BTC Von 100`")
            
            cap = 100.0
            if len(parts) > 1:
                nums = re.findall(r'\d+', parts[1])
                if nums: cap = float(''.join(nums))
                
            bot.reply_to(message, f"⏳ **Đang Backtest SMC (Chờ Đóng Nến)...**\n🪙 Coin: **{symbol}**\n🗓 Thời gian: **{'30 Ngày' if days==30 else '7 Ngày'}**\n💰 Vốn giả định: **{fmt_money(cap, 'USDT')}**\n🛡 Mức Rủi ro test: **{user.get('risk_percent', 1.0)}%**")
            threading.Thread(target=process_backtest, args=(chat_id, symbol, cap, days)).start()
        except:
            bot.reply_to(message, f"⚠️ Lỗi cú pháp Backtest!")
        return

    if text.startswith("ENTRY NOW"):
        symbol = text.replace("ENTRY NOW", "").replace("(", "").replace(")", "").strip()
        if not check_all_in_safety(user, message, [symbol]): return
        opens, highs, lows, closes, _ = lay_data_binance(symbol)
        if closes is None: return
        tin_hieu, sl, tp, ly_do, _, _, _, _, _, _ = run_smc_engine(opens[:-1], highs[:-1], lows[:-1], closes[:-1])
        if not tin_hieu:
            p_now = closes[-1]
            tin_hieu, sl, tp = "LONG 🟢", p_now*0.9995, p_now*1.001
            ly_do = "Lệnh tay khẩn cấp"
        execute_trade(chat_id, symbol, tin_hieu, ly_do, closes[-1], sl, tp)
        return
    
    if text == "SCAN":
        res = scan_market(chat_id)
        if res: 
            bot.reply_to(message, "🔍 **KÈO SMC M5:**\n" + "\n".join(res))
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
        return

    if text == "DUNG":
        user['watching'] = []
        user['auto_watching'] = [] 
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

    # Xử lý xem chart 
    symbol = text.split()[0]
    msg = bot.reply_to(message, f"🔍 Đang phân tích Chart SMC TradingView {symbol}...")
    
    opens, highs, lows, closes, src = lay_data_binance(symbol)
    if closes is not None:
        active_trade = user['active_trades'].get(symbol)
        tin_hieu, _, _, ly_do, fvgs, lines, s_high, s_low, sh_idx, sl_idx = run_smc_engine(opens, highs, lows, closes)
        
        photo = ve_chart_smc(symbol, opens, highs, lows, closes, fvgs, lines, s_high, s_low, sh_idx, sl_idx, active_trade)
        
        if active_trade:
            curr_price = closes[-1]
            if active_trade['type'] == 'LONG':
                move = (curr_price - active_trade['entry']) / active_trade['entry']
            else:
                move = (active_trade['entry'] - curr_price) / active_trade['entry']
                
            pnl = move * active_trade['leverage'] * active_trade['amount']
            pnl_sign = "+" if pnl >= 0 else ""
            status = f"⏳ Đang giữ lệnh **{active_trade['type']}**\n📈 Lãi/lỗ tạm tính: {pnl_sign}{fmt_money(pnl, 'USDT')}"
        else:
            tin_hieu_confirmed, _, _, ly_do_confirmed, _, _, _, _, _, _ = run_smc_engine(opens[:-1], highs[:-1], lows[:-1], closes[:-1])
            status = f"🚀 **{tin_hieu_confirmed}**" if tin_hieu_confirmed else "Giá đang chạy, chờ Setup."
            if ly_do_confirmed: status += f"\n({ly_do_confirmed})"
            
        caption = f"📊 **{symbol} (M5 SMC Chart)**\n🇺🇸 ${closes[-1]:,.4f}\nStatus: {status}\n📡 {src}"
        
        bot.send_photo(chat_id, photo, caption=caption, parse_mode="Markdown")
        bot.edit_message_text(f"✅ Đã vẽ xong Chart SMC cho {symbol}!", chat_id, msg.message_id) 
    else:
        gia, src, sym = lay_gia_coingecko_smart(symbol)
        if gia:
             bot.edit_message_text(f"💰 {sym}: ${gia:,.6f}\n📡 {src}", chat_id, msg.message_id)
        else:
             bot.edit_message_text("❌ Không tìm thấy coin.", chat_id, msg.message_id)

print("🤖 BOT SMC ĐANG CHẠY (GIAO DIỆN MỚI + LỆNH RỦI RO ĐỘNG)...")
threading.Thread(target=global_monitor_thread, daemon=True).start()
keep_alive()
bot.infinity_polling()

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
        res = requests.get("https://api.remitano.com/api/v1/rates/ads", timeout=3).json()
        if 'usdt' in res: return float(res['usdt']['ask'])
    except: pass
    return 26000

# --- LẤY DATA BINANCE FUTURES ---
def lay_data_binance(symbol, limit=500):
    NODES = ["https://fapi.binance.com/fapi/v1/klines", "https://api.binance.com/api/v3/klines"]
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

# --- ENGINE SMC THEO CHUẨN PINE SCRIPT (LUDOGH68) ---
def run_smc_engine(opens, highs, lows, closes):
    # Khởi tạo biến lưu trữ cho Chart và Backtest
    fvgs = [] 
    lines = [] 
    
    struct_high = highs[0]
    struct_low = lows[0]
    struct_h_idx = 0
    struct_l_idx = 0
    direction = 0 # 0: init, 1: Bearish, 2: Bullish
    
    signal, sl, tp, reason = None, 0, 0, ""

    # Chạy vòng lặp mô phỏng quá khứ như TradingView
    for i in range(10, len(closes)):
        # 1. Tìm FVG (Độ trễ 2 nến)
        # Bullish FVG
        if highs[i-2] < lows[i]:
            fvgs.append({'type': 'bull', 'top': lows[i], 'bot': highs[i-2], 'start': i-1, 'mitigated': False})
        # Bearish FVG
        if lows[i-2] > highs[i]:
            fvgs.append({'type': 'bear', 'top': lows[i-2], 'bot': highs[i], 'start': i-1, 'mitigated': False})

        # Xử lý Mitigate (Xóa hoặc làm mờ FVG nếu giá chạm)
        for f in fvgs:
            if not f['mitigated']:
                if f['type'] == 'bull' and lows[i] <= f['bot']: f['mitigated'] = True
                elif f['type'] == 'bear' and highs[i] >= f['top']: f['mitigated'] = True

        # 2. Xử lý Cấu Trúc (BOS / CHOCH)
        curr_c = closes[i]
        
        # Break Low
        if curr_c < struct_low:
            line_type = "BOS" if direction == 1 else "CHoCH"
            lines.append({'type': line_type, 'dir': 'bear', 'price': struct_low, 'start': struct_l_idx, 'end': i})
            direction = 1
            # Reset đỉnh/đáy mới
            struct_h_idx = i - 10 + np.argmax(highs[i-10:i+1])
            struct_high = highs[struct_h_idx]
            struct_low = lows[i]
            struct_l_idx = i

        # Break High
        elif curr_c > struct_high:
            line_type = "BOS" if direction == 2 else "CHoCH"
            lines.append({'type': line_type, 'dir': 'bull', 'price': struct_high, 'start': struct_h_idx, 'end': i})
            direction = 2
            # Reset đỉnh/đáy mới
            struct_l_idx = i - 10 + np.argmin(lows[i-10:i+1])
            struct_low = lows[struct_l_idx]
            struct_high = highs[i]
            struct_h_idx = i

        else:
            # Cập nhật Swing High/Low nếu chưa Break
            if highs[i] > struct_high and (direction == 0 or direction == 2):
                struct_high = highs[i]
                struct_h_idx = i
            elif lows[i] < struct_low and (direction == 0 or direction == 1):
                struct_low = lows[i]
                struct_l_idx = i

        # 3. KÍCH HOẠT LỆNH (Chỉ xét cây nến cuối cùng hiện tại để bắn tín hiệu)
        if i == len(closes) - 1:
            for f in reversed(fvgs):
                if not f['mitigated']:
                    # Lệnh LONG: Đang Uptrend (dir=2) + Chạm Bullish FVG
                    if direction == 2 and f['type'] == 'bull' and lows[i] <= f['top'] and closes[i] > f['bot']:
                        signal = "LONG 🟢"
                        reason = "Uptrend (BOS/CHoCH) + Retest FVG"
                        sl = f['bot'] * 0.9995
                        tp = closes[i] + (closes[i] - sl) * 2.0
                        break
                    # Lệnh SHORT: Đang Downtrend (dir=1) + Chạm Bearish FVG
                    elif direction == 1 and f['type'] == 'bear' and highs[i] >= f['bot'] and closes[i] < f['top']:
                        signal = "SHORT 🔴"
                        reason = "Downtrend (BOS/CHoCH) + Retest FVG"
                        sl = f['top'] * 1.0005
                        tp = closes[i] - (sl - closes[i]) * 2.0
                        break

    return signal, sl, tp, reason, fvgs, lines

# --- VẼ CHART SMC CHUẨN TRADINGVIEW ---
def ve_chart_smc(symbol, opens, highs, lows, closes, fvgs, lines):
    view = 100 # Hiển thị 100 nến
    start_idx = len(closes) - view
    
    p_o = opens[start_idx:]
    p_h = highs[start_idx:]
    p_l = lows[start_idx:]
    p_c = closes[start_idx:]
    
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor('#1e222d') # Màu nền Dark TradingView
    ax.set_facecolor('#1e222d')
    
    x = np.arange(view)
    up = p_c >= p_o
    down = p_c < p_o
    
    # Vẽ nến (Candlestick)
    ax.vlines(x[up], p_l[up], p_h[up], color='#089981', linewidth=1)
    ax.vlines(x[down], p_l[down], p_h[down], color='#f23645', linewidth=1)
    ax.bar(x[up], p_c[up] - p_o[up], 0.6, bottom=p_o[up], color='#089981')
    ax.bar(x[down], p_o[down] - p_c[down], 0.6, bottom=p_c[down], color='#f23645')

    # Vẽ FVG Boxes
    for f in fvgs:
        if f['start'] >= start_idx:
            x_start = f['start'] - start_idx
            width = view - x_start
            height = f['top'] - f['bot']
            
            # Đổi màu giống hình (Xanh/Đỏ hoặc Xám nếu Mitigated)
            if f['mitigated']:
                color = '#787b86'
                alpha = 0.1
            else:
                color = '#089981' if f['type'] == 'bull' else '#f23645'
                alpha = 0.2
                
            rect = patches.Rectangle((x_start, f['bot']), width, height, linewidth=1, edgecolor=color, facecolor=color, alpha=alpha)
            ax.add_patch(rect)
            # Thêm Text FVG
            if not f['mitigated']:
                ax.text(x_start + width/2, f['bot'] + height/2, 'FVG', color='white', fontsize=8, ha='center', va='center', alpha=0.7)

    # Vẽ đường BOS / CHoCH
    for l in lines:
        if l['start'] >= start_idx or l['end'] >= start_idx:
            x1 = max(0, l['start'] - start_idx)
            x2 = min(view, l['end'] - start_idx)
            
            line_color = '#e0e3eb' if l['type'] == 'BOS' else '#ffeb3b' # BOS xám, CHOCH vàng
            ax.plot([x1, x2], [l['price'], l['price']], color=line_color, linestyle='--', linewidth=1)
            
            # Thêm Text BOS/CHOCH
            ax.text((x1+x2)/2, l['price'], l['type'], color=line_color, fontsize=8, ha='center', va='bottom')

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
    user = get_user_data(chat_id)
    try:
        opens, highs, lows, closes, count = lay_data_lich_su(symbol, days=days)
        if closes is None or len(closes) < 150:
            bot.send_message(chat_id, f"❌ Lỗi mạng hoặc không đủ dữ liệu nến M5 để test.")
            return

        balance = start_capital
        leverage = 30
        wins, losses = 0, 0
        active_trade = None
        
        # Chạy logic SMC từng bước để Backtest
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
                    
                    balance += move * leverage * amt
                    if res == 'WIN': wins += 1
                    else: losses += 1
                    active_trade = None
                continue
            
            if balance <= (start_capital * 0.05): break 
            
            # Phân tích SMC mảng cắt ngắn để tăng tốc
            sig, sl, tp, _, _, _ = run_smc_engine(opens[i-150:i+1], highs[i-150:i+1], lows[i-150:i+1], closes[i-150:i+1])
            
            if sig:
                risk_amt = balance * 0.01
                entry = closes[i]
                dist_pct = abs(entry - sl) / entry
                if dist_pct == 0: dist_pct = 0.001
                
                margin_needed = (risk_amt / dist_pct) / leverage
                if margin_needed > balance: margin_needed = balance
                
                active_trade = {
                    'type': 'LONG' if 'LONG' in sig else 'SHORT',
                    'entry': entry, 'sl': sl, 'tp': tp, 
                    'amount': margin_needed 
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
            f"⚙️ **Đòn bẩy:** x{leverage} | **Risk:** 1%\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💵 **Vốn ban đầu:** {fmt_money(start_capital, user['currency'])}\n"
            f"🏁 **Vốn hiện tại:** {fmt_money(balance, user['currency'])}\n"
            f"📈 **Lợi nhuận (P&L):** {'+' if pnl_total >= 0 else ''}{fmt_money(pnl_total, user['currency'])} {emoji}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏆 **Thắng:** {wins} lệnh\n"
            f"🥀 **Thua:** {losses} lệnh\n"
            f"🔄 **Tổng giao dịch:** {total_trades} lệnh\n"
            f"🎯 **Tỷ lệ Win (Winrate):** {win_rate:.1f}%\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 *Thuật toán: BOS/CHoCH Structure Break + FVG.* "
        )
        bot.send_message(chat_id, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Lỗi Backtest: {e}")

# --- EXECUTE ---
def scan_market(chat_id):
    bot.send_message(chat_id, "📡 **Đang quét SMC (BOS + FVG Box)...**", parse_mode="Markdown")
    signals = []
    for symbol in WATCHLIST_MARKET:
        opens, highs, lows, closes, _ = lay_data_binance(symbol)
        if closes is not None:
            tin_hieu, _, _, _, _, _ = run_smc_engine(opens, highs, lows, closes)
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
    
    margin_needed = (risk_amount / dist_pct) / 30 
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
    bot.send_message(chat_id, "🤖 Bot SMC (BOS/CHoCH + FVG) đã sẵn sàng săn mồi 24/7...")
    while True:
        try: 
            user = get_user_data(chat_id)
            if not user['watching'] and not user['active_trades'] and not user['auto_watching']: 
                time.sleep(10)
                continue

            current_watching = list(user['watching']) 
            for symbol in current_watching:
                try: 
                    opens, highs, lows, closes, _ = lay_data_binance(symbol)
                    if closes is not None:
                        tin_hieu, sl, tp, ly_do, _, _ = run_smc_engine(opens, highs, lows, closes)
                        if tin_hieu and symbol not in user['active_trades']:
                            execute_trade(chat_id, symbol, tin_hieu, ly_do, closes[-1], sl, tp)
                            if symbol in user['watching']: user['watching'].remove(symbol)
                except: pass

            current_auto = list(user['auto_watching']) 
            for symbol in current_auto:
                try: 
                    if symbol in user['active_trades']: continue 

                    opens, highs, lows, closes, _ = lay_data_binance(symbol)
                    if closes is not None:
                        tin_hieu, sl, tp, ly_do, _, _ = run_smc_engine(opens, highs, lows, closes)
                        if tin_hieu:
                            execute_trade(chat_id, symbol, tin_hieu, ly_do, closes[-1], sl, tp)
                except: pass
            
            active_symbols = list(user['active_trades'].keys())
            for symbol in active_symbols:
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
                            
                            user['balance'] += (trade['amount'] + pnl)
                            ket_qua = "WIN 🟢" if hit_tp else "LOSS 🔴"
                            if hit_tp: user['stats']['wins'] += 1
                            else: user['stats']['losses'] += 1
                            
                            is_auto_trade = (symbol in user['auto_watching'])
                            auto_msg = "\n🔄 *Tiếp tục rình mồi SMC...*" if is_auto_trade else "\n🏁 *Đã dừng theo dõi.*"
                            
                            msg_to_send = (
                                f"🔔 **CHỐT LỆNH SMC {symbol} | {ket_qua}**\n"
                                f"━━━━━━━━━━━━━━━━━━\n"
                                f"📈 **Lợi nhuận:** {'+' if pnl >= 0 else ''}{fmt_money(pnl, user['currency'])}\n"
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
        "🚀 **3. SĂN KÈO SMC (M5 BOS + FVG):**\n"
        "   👉 `Entry now [Coin]`: Vào lệnh tay NGAY LẬP TỨC.\n"
        "   👉 `Scan`: Quét 10 coin có tín hiệu FVG/Liquidity.\n"
        "   👉 `Theo doi [Coin]`: Canh tín hiệu -> Vào lệnh -> Xong thì Dừng.\n"
        "   👉 `/Auto [Coin]`: Canh tín hiệu -> Vào lệnh -> Xong thì Lặp lại 24/7.\n\n"
        "📊 **4. TIỆN ÍCH KHÁC:**\n"
        "   👉 `Thong ke`: Xem tỷ lệ thắng/thua.\n"
        "   👉 `Reset thong ke`: Xóa sạch lịch sử Win/Loss.\n"
        "   👉 `Xem theo doi`: Xem danh sách đang canh.\n"
        "   👉 `Dung`: Dừng tất cả (Cả Auto và Theo dõi).\n"
        "   👉 Nhập tên Coin bất kỳ (VD: `PEPE`) để xem Chart M5 SMC.\n\n"
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
                else: return bot.reply_to(message, "⚠️ Nhập sai cú pháp. VD: `Backtest 1 thang BTC Von 500000`")
            
            cap = 500000 if user['currency'] == 'VNDC' else 100
            if len(parts) > 1:
                nums = re.findall(r'\d+', parts[1])
                if nums: cap = float(''.join(nums))
                
            bot.reply_to(message, f"⏳ **Đang Backtest SMC (M5)...**\n🪙 Coin: **{symbol}**\n🗓 Thời gian: **{'30 Ngày' if days==30 else '7 Ngày'}**\n💰 Vốn giả định: **{fmt_money(cap, user['currency'])}**\n⚡️ *Đang phân tích cấu trúc BOS/CHoCH, vui lòng đợi...*")
            threading.Thread(target=process_backtest, args=(chat_id, symbol, cap, days)).start()
        except:
            bot.reply_to(message, f"⚠️ Lỗi cú pháp Backtest!")
        return

    if text.startswith("ENTRY NOW"):
        symbol = text.replace("ENTRY NOW", "").replace("(", "").replace(")", "").strip()
        if not check_all_in_safety(user, message, [symbol]): return
        opens, highs, lows, closes, _ = lay_data_binance(symbol)
        if closes is None: return
        tin_hieu, sl, tp, ly_do, _, _ = run_smc_engine(opens, highs, lows, closes)
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
        if res: bot.reply_to(message, "🔍 **KÈO SMC M5:**\n" + "\n".join(res))
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
    msg = bot.reply_to(message, f"🔍 Vẽ Chart SMC TradingView {symbol}...")
    ty = lay_ty_gia_remitano()
    if ty: TY_GIA_USDT_CACHE = ty
    
    opens, highs, lows, closes, src = lay_data_binance(symbol)
    if closes is not None:
        tin_hieu, _, _, ly_do, fvgs, lines = run_smc_engine(opens, highs, lows, closes)
        photo = ve_chart_smc(symbol, opens, highs, lows, closes, fvgs, lines)
        status = f"🚀 **{tin_hieu}**" if tin_hieu else "Giá đang chạy, chờ Setup."
        if ly_do: status += f"\n({ly_do})"
        gia_vnd = closes[-1] * TY_GIA_USDT_CACHE
        caption = f"📊 **{symbol} (M5 SMC Chart)**\n🇺🇸 ${closes[-1]:,.4f}\n🇻🇳 {gia_vnd:,.0f} đ\nStatus: {status}\n📡 {src}"
        bot.send_photo(chat_id, photo, caption=caption, parse_mode="Markdown")
        bot.delete_message(chat_id, msg.message_id)
    else:
        gia, src, sym = lay_gia_coingecko_smart(symbol)
        if gia:
             gia_vnd = gia * TY_GIA_USDT_CACHE
             bot.edit_message_text(f"💰 {sym}: ${gia:,.6f} (≈ {gia_vnd:,.0f} đ)\n📡 {src}", chat_id, msg.message_id)
        else:
             bot.edit_message_text("❌ Không tìm thấy coin.", chat_id, msg.message_id)

print("🤖 BOT SMC ĐANG CHẠY (BẢN TRADINGVIEW - CHART DARK MODE)...")
keep_alive()
bot.infinity_polling()

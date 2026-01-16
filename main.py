import telebot
import requests
import numpy as np
import matplotlib.pyplot as plt
import io
import time
import threading 
import re 
import os # Thư viện để lấy mật khẩu từ két sắt Render
from keep_alive import keep_alive # Nhập file chống ngủ

# Chạy ngầm vẽ hình (Bắt buộc cho server không màn hình)
plt.switch_backend('Agg') 

# --- CẤU HÌNH BẢO MẬT ---
# Thay vì dán token lộ liễu, dòng này sẽ lấy token từ cài đặt của Render
API_TOKEN = os.environ.get('BOT_TOKEN') 

# Kiểm tra xem có lấy được token không (để debug)
if not API_TOKEN:
    print("LỖI: Chưa cài đặt biến môi trường BOT_TOKEN trên Render!")
    # Dòng dưới này chỉ để chạy thử trên máy tính cá nhân nếu cần, 
    # nhưng khi up lên GitHub thì xóa hoặc để trống nhé.
    API_TOKEN = '' 

bot = telebot.TeleBot(API_TOKEN)

# DANH SÁCH COIN
WATCHLIST_MARKET = ['BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'DOGE', 'ADA', 'AVAX', 'LINK', 'LTC', 'DOT', 'MATIC', 'TRX', 'SHIB', 'NEAR', 'PEPE', 'WIF', 'BONK', 'ARB', 'OP', 'SUI', 'APT', 'FIL', 'ATOM', 'FTM', 'SAND']

USER_DATA = {}
TY_GIA_USDT_CACHE = 26000 
LOCK = threading.Lock() 

# --- HÀM HỖ TRỢ ---
def get_user_data(chat_id):
    if chat_id not in USER_DATA:
        USER_DATA[chat_id] = {
            'balance': 500000,    
            'bet_amount': 50000,  
            'watching': [],       
            'active_trades': {},
            'stats': {'wins': 0, 'losses': 0}
        }
    return USER_DATA[chat_id]

# --- DATA & INDICATORS ---
def lay_ty_gia_remitano():
    try:
        url = "https://api.remitano.com/api/v1/rates/ads"
        res = requests.get(url, timeout=3).json()
        if 'usdt' in res: return float(res['usdt']['ask'])
    except: pass
    return None

def lay_data_binance(symbol, limit=500):
    try:
        pair = symbol.upper() + "USDT"
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval=1m&limit={limit}"
        
        # --- THÊM ĐOẠN NÀY ĐỂ NGỤY TRANG ---
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        # -----------------------------------
        
        data = requests.get(url, headers=headers, timeout=5).json() # Thêm headers vào đây
        
        if isinstance(data, list) and len(data) > 0:
            opens = [float(x[1]) for x in data]
            highs = [float(x[2]) for x in data]
            lows = [float(x[3]) for x in data]
            closes = [float(x[4]) for x in data]
            volumes = [float(x[5]) for x in data]
            return np.array(opens), np.array(highs), np.array(lows), np.array(closes), np.array(volumes), "Binance"
    except Exception as e:
        print(f"Lỗi lấy data Binance: {e}") # In lỗi ra để dễ kiểm tra
        pass
    return None, None, None, None, None, None

def lay_data_lich_su(symbol, days=7):
    try:
        pair = symbol.upper() + "USDT"
        limit_per_req = 1000
        total_candles = days * 1440
        rounds = int(total_candles / limit_per_req) + 2
        
        all_open, all_high, all_low, all_close, all_vol = [], [], [], [], []
        end_time = int(time.time() * 1000) 
        
        for _ in range(rounds):
            url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval=1m&limit={limit_per_req}&endTime={end_time}"
            data = requests.get(url, timeout=5).json()
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
        # Cũng thêm headers y chang vậy
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
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

def calculate_indicators(prices, volumes):
    def pd_ewm(data, span):
        alpha = 2 / (span + 1)
        ema = [data[0]]
        for price in data[1:]:
            ema.append(alpha * price + (1 - alpha) * ema[-1])
        return np.array(ema)

    def get_rsi(data, period=14):
        deltas = np.diff(data)
        seed = deltas[:period+1]
        up = seed[seed >= 0].sum()/period
        down = -seed[seed < 0].sum()/period
        if down == 0: down = 1e-10
        rs = up/down
        rsi = np.zeros_like(data)
        rsi[:period] = 100. - 100./(1. + rs)
        for i in range(period, len(data)):
            delta = deltas[i-1]
            if delta > 0: upval, downval = delta, 0.
            else: upval, downval = 0., -delta
            up = (up * (period - 1) + upval) / period
            down = (down * (period - 1) + downval) / period
            if down == 0: down = 1e-10
            rs = up/down
            rsi[i] = 100. - 100./(1. + rs)
        return rsi
    
    def get_sma(data, window):
        return np.convolve(data, np.ones(window), 'valid') / window

    ema9 = pd_ewm(prices, 9)
    ema21 = pd_ewm(prices, 21)
    rsi = get_rsi(prices, 14)
    vol_sma = np.zeros_like(volumes)
    sma_vals = get_sma(volumes, 20)
    # Fix lỗi lệch size array
    if len(sma_vals) > 0:
        vol_sma[len(volumes)-len(sma_vals):] = sma_vals 

    return {'ema9': ema9, 'ema21': ema21, 'rsi': rsi, 'vol_sma': vol_sma}

def kiem_tra_tin_hieu(opens, highs, lows, closes, volumes, inds):
    if len(closes) < 30: return None, 0, 0, ""
    i = -1 
    p_close = closes[i]
    p_open = opens[i]
    vol_now = volumes[i]
    ema9 = inds['ema9'][i]
    ema21 = inds['ema21'][i]
    rsi = inds['rsi'][i]
    rsi_prev = inds['rsi'][i-1]
    vol_avg = inds['vol_sma'][i]
    
    tin_hieu = None
    sl, tp = 0, 0
    ly_do = ""

    if (p_close > ema9) and (p_close > ema21) and (p_close > p_open):
        if (40 <= rsi <= 55) and (rsi > rsi_prev) and (vol_now > vol_avg):
            tin_hieu = "LONG 🟢"
            ly_do = "Price > EMAs + RSI Up (40-55) + High Vol"
            sl = min(lows[i], ema21) * 0.998
            tp = p_close + (p_close - sl) * 2.0

    if (p_close < ema9) and (p_close < ema21) and (p_close < p_open):
        if (45 <= rsi <= 60) and (rsi < rsi_prev) and (vol_now > vol_avg):
            tin_hieu = "SHORT 🔴"
            ly_do = "Price < EMAs + RSI Down (45-60) + High Vol"
            sl = max(highs[i], ema21) * 1.002
            tp = p_close - (sl - p_close) * 2.0

    return tin_hieu, sl, tp, ly_do

# --- BACKTEST ---
def process_backtest(chat_id, symbol, start_capital, days):
    try:
        opens, highs, lows, closes, vols, count = lay_data_lich_su(symbol, days=days)
        if closes is None or len(closes) < 100:
            bot.send_message(chat_id, f"❌ Không tải được dữ liệu cho {symbol}.")
            return

        inds = calculate_indicators(closes, vols)
        balance = start_capital
        leverage = 20
        wins = 0
        losses = 0
        active_trade = None
        
        for i in range(50, len(closes)-1):
            if active_trade:
                high = highs[i]
                low = lows[i]
                res = None
                if active_trade['type'] == 'LONG':
                    if low <= active_trade['sl']: res = 'LOSS'
                    elif high >= active_trade['tp']: res = 'WIN'
                else: 
                    if high >= active_trade['sl']: res = 'LOSS'
                    elif low <= active_trade['tp']: res = 'WIN'
                
                if res:
                    entry = active_trade['entry']
                    amt = active_trade['amount']
                    if res == 'WIN':
                        wins += 1
                        move = (active_trade['tp'] - entry)/entry if active_trade['type'] == 'LONG' else (entry - active_trade['tp'])/entry
                    else:
                        losses += 1
                        move = (active_trade['sl'] - entry)/entry if active_trade['type'] == 'LONG' else (entry - active_trade['sl'])/entry
                    
                    pnl = move * leverage * amt
                    balance += pnl
                    if balance < 0: balance = 0
                    active_trade = None
                continue
            
            if balance <= 10000: break
            
            p_c = closes[i]
            p_o = opens[i]
            e9 = inds['ema9'][i]
            e21 = inds['ema21'][i]
            r = inds['rsi'][i]
            r_prev = inds['rsi'][i-1]
            v = vols[i]
            v_avg = inds['vol_sma'][i]
            
            if (p_c > e9) and (p_c > e21) and (p_c > p_o):
                if (40 <= r <= 55) and (r > r_prev) and (v > v_avg):
                    sl = min(lows[i], e21) * 0.998
                    tp = p_c + (p_c - sl) * 2.0
                    active_trade = {'type':'LONG', 'entry':p_c, 'sl':sl, 'tp':tp, 'amount':balance}
            
            elif (p_c < e9) and (p_c < e21) and (p_c < p_o):
                 if (45 <= r <= 60) and (r < r_prev) and (v > v_avg):
                    sl = max(highs[i], e21) * 1.002
                    tp = p_c - (sl - p_c) * 2.0
                    active_trade = {'type':'SHORT', 'entry':p_c, 'sl':sl, 'tp':tp, 'amount':balance}

        total_trades = wins + losses
        win_rate = (wins/total_trades * 100) if total_trades > 0 else 0
        pnl_total = balance - start_capital
        emoji = "🤑 LÃI" if pnl_total >= 0 else "🩸 LỖ"
        if balance < 10000: emoji = "💀 CHÁY TK"

        msg = (
            f"📊 **BACKTEST SCALPING ({days} NGÀY)**\n"
            f"Coin: **{symbol}**\n"
            f"Số nến: {count}\n"
            f"--------------------------\n"
            f"💵 Vốn đầu: {start_capital:,.0f} đ\n"
            f"🏁 Vốn cuối: {balance:,.0f} đ\n"
            f"📈 **P&L: {pnl_total:+,.0f} đ** ({emoji})\n"
            f"--------------------------\n"
            f"🏆 Thắng: {wins} | 🥀 Thua: {losses}\n"
            f"🔄 Tổng lệnh: {total_trades}\n"
            f"💎 **Tỷ lệ Win: {win_rate:.1f}%**\n"
            f"--------------------------\n"
            f"⚙️ Cơ chế: All-in từng lệnh x20"
        )
        bot.send_message(chat_id, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Lỗi: {e}")

def ve_chart(symbol, prices, inds):
    view = 80 
    p_view = prices[-view:]
    ema9_v = inds['ema9'][-view:]
    ema21_v = inds['ema21'][-view:]
    rsi_v = inds['rsi'][-view:]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 10), gridspec_kw={'height_ratios': [3, 2]})
    fig.tight_layout(pad=5.0)

    ax1.plot(p_view, color='black', alpha=0.6, label='Price')
    ax1.plot(ema9_v, color='#0099ff', label='EMA 9')
    ax1.plot(ema21_v, color='#FFD700', label='EMA 21')
    ax1.set_title(f'{symbol} (1m) Scalping')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    ax2.plot(rsi_v, color='purple', label='RSI')
    ax2.axhline(50, color='gray', linestyle='--')
    ax2.fill_between(range(len(rsi_v)), rsi_v, 50, where=(rsi_v >= 50), color='green', alpha=0.3)
    ax2.fill_between(range(len(rsi_v)), rsi_v, 50, where=(rsi_v < 50), color='red', alpha=0.3)
    ax2.set_ylim(20, 80)
    
    txt = f"RSI: {inds['rsi'][-1]:.1f}"
    props = dict(boxstyle='round', facecolor='white', alpha=0.9)
    ax2.text(0.02, 0.95, txt, transform=ax2.transAxes, bbox=props, verticalalignment='top')
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

def scan_market(chat_id):
    bot.send_message(chat_id, "📡 **Đang quét tín hiệu Scalping (1m)...**", parse_mode="Markdown")
    signals, potentials = [], []
    for symbol in WATCHLIST_MARKET:
        opens, highs, lows, closes, vols, _ = lay_data_binance(symbol)
        if closes is not None:
            inds = calculate_indicators(closes, vols)
            tin_hieu, _, _, _ = kiem_tra_tin_hieu(opens, highs, lows, closes, vols, inds)
            rsi = inds['rsi'][-1]
            vol_now = vols[-1]
            vol_avg = inds['vol_sma'][-1]
            
            if tin_hieu:
                signals.append(f"🔥 {symbol}: {tin_hieu} (Vol x{vol_now/vol_avg:.1f})")
                continue
            if 38 <= rsi <= 42: potentials.append(f"👀 {symbol}: RSI {rsi:.0f} (Chờ Long)")
            if 58 <= rsi <= 62: potentials.append(f"👀 {symbol}: RSI {rsi:.0f} (Chờ Short)")
    return (signals + potentials)[:10]

def execute_trade(chat_id, symbol, tin_hieu, ly_do, entry, sl, tp):
    user = get_user_data(chat_id)
    if user['balance'] <= 0:
        bot.send_message(chat_id, "❌ **Hết tiền rồi!**")
        return

    trade_amount = user['bet_amount']
    is_all_in = False
    if user['balance'] < user['bet_amount']:
        trade_amount = user['balance']
        is_all_in = True
    
    leverage = 20
    user['balance'] -= trade_amount
    
    user['active_trades'][symbol] = {
        'type': 'LONG' if 'LONG' in tin_hieu else 'SHORT',
        'entry': entry, 'sl': sl, 'tp': tp,
        'amount': trade_amount, 'leverage': leverage
    }
    
    global TY_GIA_USDT_CACHE
    entry_vnd = entry * TY_GIA_USDT_CACHE
    sl_vnd = sl * TY_GIA_USDT_CACHE
    tp_vnd = tp * TY_GIA_USDT_CACHE
    note = " (ALL-IN 🔥)" if is_all_in else ""
    
    msg = (
        f"🚀 **ENTRY NOW: {symbol}**\n--------------------\n"
        f"Loại: **{tin_hieu}**\nLý do: {ly_do}\n--------------------\n"
        f"Entry: **${entry:,.4f}** (≈ {entry_vnd:,.0f} đ)\n"
        f"Vốn: **{trade_amount:,.0f} đ**{note}\n"
        f"🛑 SL: **${sl:,.4f}**\n🎯 TP: **${tp:,.4f}**\n"
        f"--------------------\n💰 Còn lại: {user['balance']:,.0f} đ"
    )
    bot.send_message(chat_id, msg, parse_mode="Markdown")

def monitor_thread(chat_id):
    user = get_user_data(chat_id)
    while True:
        if not user['watching'] and not user['active_trades']: break
        try:
            ty = lay_ty_gia_remitano()
            if ty: 
                global TY_GIA_USDT_CACHE
                TY_GIA_USDT_CACHE = ty

            current_watching = list(user['watching']) 
            for symbol in current_watching:
                opens, highs, lows, closes, vols, _ = lay_data_binance(symbol)
                if closes is not None:
                    inds = calculate_indicators(closes, vols)
                    tin_hieu, sl, tp, ly_do = kiem_tra_tin_hieu(opens, highs, lows, closes, vols, inds)
                    if tin_hieu and symbol not in user['active_trades']:
                        execute_trade(chat_id, symbol, tin_hieu, ly_do, closes[-1], sl, tp)
                        if symbol in user['watching']: user['watching'].remove(symbol)

            active_symbols = list(user['active_trades'].keys())
            for symbol in active_symbols:
                trade = user['active_trades'][symbol]
                _, _, _, closes, _, _ = lay_data_binance(symbol)
                if closes is not None:
                    curr = closes[-1]
                    if trade['type'] == 'LONG':
                        hit_tp = curr >= trade['tp']
                        hit_sl = curr <= trade['sl']
                        move = (curr - trade['entry']) / trade['entry']
                    else: 
                        hit_tp = curr <= trade['tp']
                        hit_sl = curr >= trade['sl']
                        move = (trade['entry'] - curr) / trade['entry']

                    if hit_tp or hit_sl:
                        pnl = move * trade['leverage'] * trade['amount']
                        user['balance'] += (trade['amount'] + pnl)
                        ket_qua = "WIN 🟢" if hit_tp else "LOSS 🔴"
                        if hit_tp: user['stats']['wins'] += 1
                        else: user['stats']['losses'] += 1
                        bot.send_message(chat_id, f"🔔 **KẾT THÚC {symbol}: {ket_qua}**\nLãi/Lỗ: {pnl:+,.0f} đ\n💰 Vốn mới: {user['balance']:,.0f} đ", parse_mode="Markdown")
                        del user['active_trades'][symbol]
        except: pass
        time.sleep(60)

# --- BOT COMMANDS ---
@bot.message_handler(commands=['start', 'help'])
def send_help(message):
    user = get_user_data(message.chat.id)
    help_text = (
        "📖 **HƯỚNG DẪN SỬ DỤNG BOT SCALPING** 📖\n\n"
        "🛠 **1. CÀI ĐẶT & VỐN:**\n"
        "   👉 `/Von [Số tiền]`: Cài tổng vốn (Ví dụ: `Von 1000000`)\n"
        "   👉 `/Cuoc [Số tiền]`: Cài tiền đi lệnh (Ví dụ: `Cuoc 50000`)\n"
        "   👉 `Xem von`: Kiểm tra số dư hiện tại.\n\n"
        "🧪 **2. BACKTEST (KIỂM TRA QUÁ KHỨ):**\n"
        "   👉 `Backtest [Coin] Von [Tiền]`: Test 7 ngày.\n"
        "      - VD: `Backtest BTC Von 500000`\n"
        "   👉 `Backtest 1 thang [Coin] Von [Tiền]`: Test 30 ngày.\n"
        "      - VD: `Backtest 1 thang ETH Von 200000`\n"
        "   ℹ️ *Bot sẽ hiện: Tổng lệnh Thắng/Thua, Tỷ lệ Win, Lãi/Lỗ cuối cùng.*\n\n"
        "🚀 **3. GIAO DỊCH (TRADE):**\n"
        "   👉 `Entry now [Coin]`: Vào lệnh NGAY LẬP TỨC (Long/Short theo EMA).\n"
        "   👉 `Scan`: Quét 10 coin có tín hiệu Scalping đẹp.\n"
        "   👉 `Theo doi [Coin]`: Bot tự động canh 24/7, có kèo là vào.\n"
        "      - VD: `Theo doi BTC SOL DOGE`\n\n"
        "📊 **4. TIỆN ÍCH KHÁC:**\n"
        "   👉 `Thong ke`: Xem tỷ lệ thắng/thua thực tế của bạn.\n"
        "   👉 `Xem theo doi`: Xem danh sách đang canh.\n"
        "   👉 `Dung`: Dừng theo dõi tất cả.\n"
        "   👉 Nhập tên Coin bất kỳ (VD: `PEPE`) để xem Chart + Tín hiệu.\n\n"
        "--------------------------\n"
        f"💰 Vốn: **{user['balance']:,.0f} đ**\n"
        f"💵 Cược: **{user['bet_amount']:,.0f} đ**"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_msg(message):
    text = message.text.strip().upper()
    chat_id = message.chat.id
    user = get_user_data(chat_id)
    
    # SETTINGS
    if text.startswith("VON "):
        try:
            user['balance'] = int(''.join(filter(str.isdigit, text)))
            bot.reply_to(message, f"✅ Đã set vốn: {user['balance']:,.0f} đ")
        except: pass
        return
    if text.startswith("CUOC "):
        try:
            user['bet_amount'] = int(''.join(filter(str.isdigit, text)))
            bot.reply_to(message, f"✅ Đã set cược: {user['bet_amount']:,.0f} đ")
        except: pass
        return
    if text in ["XEM VON", "VỐN"]:
        bot.reply_to(message, f"💰 Vốn: {user['balance']:,.0f} đ")
        return

    # BACKTEST
    if text.startswith("BACKTEST"):
        try:
            days = 30 if "1 THANG" in text or "1 THÁNG" in text else 7
            clean_text = text.replace("BACKTEST", "").replace("1 THANG", "").replace("1 THÁNG", "").replace("VON", "")
            match = re.search(r'\b[A-Z0-9]+\b', clean_text)
            if not match: 
                bot.reply_to(message, "⚠️ Nhập tên Coin. VD: `Backtest BTC Von 200k`")
                return
            symbol = match.group(0)
            
            cap = 500000
            if "VON" in text:
                nums = re.findall(r'\d+', text.split("VON")[1])
                if nums: cap = int(''.join(nums))

            t_str = "1 Tháng" if days==30 else "7 Ngày"
            bot.reply_to(message, f"⏳ Đang Backtest {t_str} Scalping cho {symbol}...\n(Vốn giả định: {cap:,.0f}đ)")
            threading.Thread(target=process_backtest, args=(chat_id, symbol, cap, days)).start()
        except: pass
        return

    # ENTRY NOW
    if text.startswith("ENTRY NOW"):
        symbol = text.replace("ENTRY NOW", "").replace("(", "").replace(")", "").strip()
        opens, highs, lows, closes, vols, _ = lay_data_binance(symbol)
        if closes is None: return

        inds = calculate_indicators(closes, vols)
        p_now = closes[-1]
        ema9 = inds['ema9'][-1]
        ema21 = inds['ema21'][-1]
        
        if p_now > ema9 and p_now > ema21:
            direc = "LONG 🟢 (Trend EMA)"
            sl = min(lows[-1], ema21) * 0.998
            tp = p_now + (p_now - sl) * 2.0
        else:
            direc = "SHORT 🔴 (Trend EMA)"
            sl = max(highs[-1], ema21) * 1.002
            tp = p_now - (sl - p_now) * 2.0

        execute_trade(chat_id, symbol, direc, "Lệnh Tay", p_now, sl, tp)
        threading.Thread(target=monitor_thread, args=(chat_id,)).start()
        return

    # SCAN, THEO DOI...
    if text == "SCAN":
        res = scan_market(chat_id)
        if res: bot.reply_to(message, "🔍 **KÈO SCALPING:**\n" + "\n".join(res))
        else: bot.reply_to(message, "Chưa có tín hiệu đẹp.")
        return

    if text.startswith("THEO DOI"):
        coins = text.replace("THEO DOI", "").replace(",", " ").split()
        valid = [c.strip().upper() for c in coins if c.strip()][:5]
        if valid:
            user['watching'] = valid
            bot.reply_to(message, f"📡 Đang canh Scalping: {', '.join(valid)}")
            threading.Thread(target=monitor_thread, args=(chat_id,)).start()
        return

    if text == "DUNG":
        user['watching'] = []
        bot.reply_to(message, "🛑 Đã dừng.")
        return
    
    if text in ["THONG KE", "THỐNG KÊ"]:
        w, l = user['stats']['wins'], user['stats']['losses']
        rate = w/(w+l)*100 if (w+l)>0 else 0
        bot.reply_to(message, f"📊 Win: {w} | Loss: {l} ({rate:.1f}%)")
        return
    
    if text in ["XEM THEO DOI", "LIST"]:
        if user['watching']: bot.reply_to(message, f"📋 List: {', '.join(user['watching'])}")
        else: bot.reply_to(message, "📭 Trống.")
        return

    # CHECK COIN
    symbol = text.split()[0]
    msg = bot.reply_to(message, f"🔍 Check {symbol}...")
    ty = lay_ty_gia_remitano()
    if ty: 
        global TY_GIA_USDT_CACHE
        TY_GIA_USDT_CACHE = ty
    
    opens, highs, lows, closes, vols, src = lay_data_binance(symbol)
    if closes is not None:
        inds = calculate_indicators(closes, vols)
        photo = ve_chart(symbol, closes, inds)
        tin_hieu, _, _, ly_do = kiem_tra_tin_hieu(opens, highs, lows, closes, vols, inds)
        status = f"🚀 **{tin_hieu}**" if tin_hieu else "Chờ tín hiệu."
        if ly_do: status += f"\n({ly_do})"
        
        gia_vnd = closes[-1] * TY_GIA_USDT_CACHE
        caption = f"📊 **{symbol} (1m Scalp)**\n🇺🇸 ${closes[-1]:,.4f}\n🇻🇳 {gia_vnd:,.0f} đ\nStatus: {status}\n📡 {src}"
        bot.send_photo(chat_id, photo, caption=caption, parse_mode="Markdown")
        bot.delete_message(chat_id, msg.message_id)
    else:
        gia, src, sym = lay_gia_coingecko_smart(symbol)
        if gia:
             gia_vnd = gia * TY_GIA_USDT_CACHE
             txt = f"💰 {sym}: ${gia:,.6f} (≈ {gia_vnd:,.0f} đ)\n📡 {src}"
             bot.edit_message_text(txt, chat_id, msg.message_id)
        else:
             bot.edit_message_text("❌ Không tìm thấy.", chat_id, msg.message_id)

print("🤖 BOT COMPLETE ĐANG CHẠY...")
# Kích hoạt server chống ngủ
keep_alive()

bot.infinity_polling()

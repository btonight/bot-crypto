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
    API_TOKEN = 'TOKEN_TEST_CUA_BAN' 

bot = telebot.TeleBot(API_TOKEN)

# DANH SÁCH COIN
WATCHLIST_MARKET = ['BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'DOGE', 'ADA', 'AVAX', 'LINK', 'LTC', 'DOT', 'MATIC', 'TRX', 'SHIB', 'NEAR', 'PEPE', 'WIF', 'BONK', 'ARB', 'OP', 'SUI', 'APT', 'FIL', 'ATOM', 'FTM', 'SAND']

USER_DATA = {}
TY_GIA_USDT_CACHE = 26000 

# --- HÀM HỖ TRỢ ---
def get_user_data(chat_id):
    if chat_id not in USER_DATA:
        USER_DATA[chat_id] = {
            'balance': 500000,    
            'bet_amount': 50000,  
            'watching': [],       
            'auto_watching': [],  
            'active_trades': {},
            'stats': {'wins': 0, 'losses': 0}
        }
    return USER_DATA[chat_id]

def lay_ty_gia_remitano():
    try:
        url = "https://api.remitano.com/api/v1/rates/ads"
        res = requests.get(url, timeout=3).json()
        if 'usdt' in res: return float(res['usdt']['ask'])
    except: pass
    return 26000

# --- LẤY DATA BINANCE ---
def lay_data_binance(symbol, limit=500):
    NODES = [
        "https://api.binance.com", 
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
        "https://data-api.binance.vision"
    ]
    pair = symbol.upper() + "USDT"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

    for node in NODES:
        try:
            url = f"{node}/api/v3/klines?symbol={pair}&interval=1m&limit={limit}"
            data = requests.get(url, headers=headers, timeout=2).json()
            if isinstance(data, list) and len(data) > 0:
                opens = [float(x[1]) for x in data]
                highs = [float(x[2]) for x in data]
                lows = [float(x[3]) for x in data]
                closes = [float(x[4]) for x in data]
                volumes = [float(x[5]) for x in data]
                return np.array(opens), np.array(highs), np.array(lows), np.array(closes), np.array(volumes), "Binance"
        except: continue
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

# --- CHỈ BÁO ---
def calculate_indicators(closes, highs, lows, volumes):
    def get_rsi(data, period=7):
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
            rs = up/down
            rsi[i] = 100. - 100./(1. + rs)
        return rsi

    typical_price = (highs + lows + closes) / 3
    cum_pv = np.cumsum(typical_price * volumes)
    cum_vol = np.cumsum(volumes)
    with np.errstate(divide='ignore', invalid='ignore'):
        vwap = np.where(cum_vol == 0, 0, cum_pv / cum_vol)

    sma20 = np.zeros_like(closes)
    std20 = np.zeros_like(closes)
    for i in range(20, len(closes)):
        window = closes[i-20:i]
        sma20[i] = np.mean(window)
        std20[i] = np.std(window)
    bb_upper = sma20 + (2 * std20)
    bb_lower = sma20 - (2 * std20)
    
    rsi7 = get_rsi(closes, 7)
    
    vol_sma = np.zeros_like(volumes)
    for i in range(20, len(volumes)):
        vol_sma[i] = np.mean(volumes[i-20:i])

    return {'vwap': vwap, 'bb_upper': bb_upper, 'bb_lower': bb_lower, 'rsi': rsi7, 'vol_sma': vol_sma}

# --- TÍN HIỆU (HARDCORE MODE - KHÓ TÍNH) ---
def kiem_tra_tin_hieu(opens, highs, lows, closes, volumes, inds):
    if len(closes) < 30: return None, 0, 0, ""
    
    i = -1 
    p_close = closes[i]
    p_open = opens[i]
    p_high = highs[i]
    p_low = lows[i]
    vwap = inds['vwap'][i]
    bb_upper = inds['bb_upper'][i]
    bb_lower = inds['bb_lower'][i]
    rsi = inds['rsi'][i]
    vol_now = volumes[i]
    vol_avg = inds['vol_sma'][i]
    
    tin_hieu = None
    sl, tp = 0, 0
    ly_do = ""

    # Setup 1: VWAP Pullback (QUAY LẠI CHẾ ĐỘ 3 ĐIỀU KIỆN)
    # Điều kiện:
    # 1. Chạm cực sát VWAP (0.1%)
    # 2. RSI chuẩn form (40-55)
    # 3. Volume > Trung bình (Tiền phải vào)
    
    if p_close > vwap: 
        if (p_low <= vwap * 1.001) and (p_close > p_open): # Chạm sát + Nến xanh
            if (40 <= rsi <= 55) and (vol_now > vol_avg): # RSI đẹp + Vol to
                tin_hieu = "LONG (VWAP Pullback) 🟢"
                ly_do = "Trend Lên + Chạm VWAP + Vol tốt"
                # SL 0.3% (Giữ nguyên cái bạn thích)
                sl = min(p_low, vwap) * 0.997 
                # TP x2.0
                tp = p_close + (p_close - sl) * 2.0

    elif p_close < vwap: 
        if (p_high >= vwap * 0.999) and (p_close < p_open): # Chạm sát + Nến đỏ
            if (45 <= rsi <= 60) and (vol_now > vol_avg): # RSI đẹp + Vol to
                tin_hieu = "SHORT (VWAP Pullback) 🔴"
                ly_do = "Trend Xuống + Chạm VWAP + Vol tốt"
                sl = max(p_high, vwap) * 1.003
                tp = p_close - (sl - p_close) * 2.0

    # Setup 2: BB Bounce (Cũng phải có Volume mới chơi)
    if not tin_hieu:
        if (p_low <= bb_lower) and (p_close > bb_lower) and (p_close > p_open):
            if (rsi <= 35) and (vol_now > vol_avg): # Thêm điều kiện Vol
                tin_hieu = "LONG (BB Bounce) 🟢"
                ly_do = "Chạm Band Dưới + RSI quá bán + Vol tốt"
                sl = p_low * 0.997
                tp = p_close + (p_close - sl) * 2.0 

        elif (p_high >= bb_upper) and (p_close < bb_upper) and (p_close < p_open):
            if (rsi >= 65) and (vol_now > vol_avg): # Thêm điều kiện Vol
                tin_hieu = "SHORT (BB Bounce) 🔴"
                ly_do = "Chạm Band Trên + RSI quá mua + Vol tốt"
                sl = p_high * 1.003
                tp = p_close - (sl - p_close) * 2.0

    return tin_hieu, sl, tp, ly_do

# --- BACKTEST (CẬP NHẬT LOGIC HARDCORE) ---
def process_backtest(chat_id, symbol, start_capital, days):
    try:
        opens, highs, lows, closes, vols, count = lay_data_lich_su(symbol, days=days)
        if closes is None or len(closes) < 100:
            bot.send_message(chat_id, f"❌ Không tải được dữ liệu.")
            return

        inds = calculate_indicators(closes, highs, lows, vols)
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
            p_l = lows[i]
            p_h = highs[i]
            vwap = inds['vwap'][i]
            bbl = inds['bb_lower'][i]
            bbu = inds['bb_upper'][i]
            rsi = inds['rsi'][i]
            v_now = vols[i]
            v_avg = inds['vol_sma'][i]
            
            # Logic Hardcore (3 điều kiện)
            if (p_c > vwap) and (p_l <= vwap * 1.001) and (p_c > p_o) and (40 <= rsi <= 55) and (v_now > v_avg):
                sl = min(p_l, vwap) * 0.997
                tp = p_c + (p_c - sl) * 2.0
                active_trade = {'type':'LONG', 'entry':p_c, 'sl':sl, 'tp':tp, 'amount':balance}
            elif (p_c < vwap) and (p_h >= vwap * 0.999) and (p_c < p_o) and (45 <= rsi <= 60) and (v_now > v_avg):
                sl = max(p_h, vwap) * 1.003
                tp = p_c - (sl - p_c) * 2.0
                active_trade = {'type':'SHORT', 'entry':p_c, 'sl':sl, 'tp':tp, 'amount':balance}
            elif (p_l <= bbl) and (p_c > bbl) and (rsi <= 35) and (v_now > v_avg):
                sl = p_l * 0.997
                tp = p_c + (p_c - sl) * 2.0
                active_trade = {'type':'LONG', 'entry':p_c, 'sl':sl, 'tp':tp, 'amount':balance}
            elif (p_h >= bbu) and (p_c < bbu) and (rsi >= 65) and (v_now > v_avg):
                sl = p_h * 1.003
                tp = p_c - (sl - p_c) * 2.0
                active_trade = {'type':'SHORT', 'entry':p_c, 'sl':sl, 'tp':tp, 'amount':balance}

        total_trades = wins + losses
        win_rate = (wins/total_trades * 100) if total_trades > 0 else 0
        pnl_total = balance - start_capital
        emoji = "🤑 LÃI" if pnl_total >= 0 else "🩸 LỖ"
        if balance < 10000: emoji = "💀 CHÁY TK"

        msg = (
            f"📊 **BACKTEST ({days} NGÀY) - HARDCORE MODE**\n"
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
        )
        bot.send_message(chat_id, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Lỗi: {e}")

def ve_chart(symbol, prices, inds):
    view = 80 
    p_view = prices[-view:]
    vwap_v = inds['vwap'][-view:]
    bbu_v = inds['bb_upper'][-view:]
    bbl_v = inds['bb_lower'][-view:]
    rsi_v = inds['rsi'][-view:]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 10), gridspec_kw={'height_ratios': [3, 2]})
    fig.tight_layout(pad=5.0)

    ax1.plot(p_view, color='black', alpha=0.6, label='Price')
    ax1.plot(vwap_v, color='#FF8C00', label='VWAP (Cam)', linewidth=2)
    ax1.plot(bbu_v, color='gray', linestyle=':', alpha=0.5)
    ax1.plot(bbl_v, color='gray', linestyle=':', alpha=0.5)
    ax1.fill_between(range(len(p_view)), bbu_v, bbl_v, color='gray', alpha=0.1)
    ax1.set_title(f'{symbol} (1m) Price Action')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)

    ax2.plot(rsi_v, color='purple', label='RSI (7)')
    ax2.axhline(65, color='red', linestyle=':')
    ax2.axhline(35, color='green', linestyle=':')
    ax2.set_title('RSI (7) Momentum')
    ax2.set_ylim(10, 90)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

# --- EXECUTE ---
def scan_market(chat_id):
    bot.send_message(chat_id, "📡 **Đang quét tín hiệu (Hardcore + Vol)...**", parse_mode="Markdown")
    signals = []
    for symbol in WATCHLIST_MARKET:
        opens, highs, lows, closes, vols, _ = lay_data_binance(symbol)
        if closes is not None:
            inds = calculate_indicators(closes, highs, lows, vols)
            tin_hieu, _, _, _ = kiem_tra_tin_hieu(opens, highs, lows, closes, vols, inds)
            if tin_hieu:
                signals.append(f"🔥 {symbol}: {tin_hieu}")
    return signals[:10]

def execute_trade(chat_id, symbol, tin_hieu, ly_do, entry, sl, tp, is_auto=False):
    user = get_user_data(chat_id)
    if user['balance'] <= 0:
        bot.send_message(chat_id, "❌ **Hết tiền Demo rồi!**")
        return
    trade_amount = user['bet_amount']
    if user['balance'] < user['bet_amount']: trade_amount = user['balance']
    user['balance'] -= trade_amount
    
    user['active_trades'][symbol] = {
        'type': 'LONG' if 'LONG' in tin_hieu else 'SHORT',
        'entry': entry, 'sl': sl, 'tp': tp, 
        'amount': trade_amount, 'leverage': 20,
        'is_auto': is_auto 
    }
    
    global TY_GIA_USDT_CACHE
    entry_vnd = entry * TY_GIA_USDT_CACHE
    
    auto_tag = " (AUTO LOOP 🔄)" if is_auto else ""
    
    msg = (
        f"🚀 **ENTRY NOW: {symbol}{auto_tag}**\n--------------------\n"
        f"Loại: **{tin_hieu}**\nLý do: {ly_do}\n--------------------\n"
        f"Entry: **${entry:,.4f}** (≈ {entry_vnd:,.0f} đ)\n"
        f"Vốn: **{trade_amount:,.0f} đ** (Demo)\n"
        f"🛑 SL: **${sl:,.4f}**\n🎯 TP: **${tp:,.4f}**\n"
        f"--------------------\n💰 Còn lại: {user['balance']:,.0f} đ"
    )
    bot.send_message(chat_id, msg, parse_mode="Markdown")

# --- MONITOR 24/7 ---
def monitor_thread(chat_id):
    bot.send_message(chat_id, "🤖 Bot bắt đầu canh lệnh 24/7 (Hardcore Mode)...")
    while True:
        try: 
            user = get_user_data(chat_id)
            if not user['watching'] and not user['active_trades'] and not user['auto_watching']: 
                time.sleep(10)
                continue

            # 1. Quét list THEO DÕI (1 lần)
            current_watching = list(user['watching']) 
            for symbol in current_watching:
                try: 
                    opens, highs, lows, closes, vols, _ = lay_data_binance(symbol)
                    if closes is not None:
                        inds = calculate_indicators(closes, highs, lows, vols)
                        tin_hieu, sl, tp, ly_do = kiem_tra_tin_hieu(opens, highs, lows, closes, vols, inds)
                        if tin_hieu and symbol not in user['active_trades']:
                            execute_trade(chat_id, symbol, tin_hieu, ly_do, closes[-1], sl, tp, is_auto=False)
                            if symbol in user['watching']: user['watching'].remove(symbol)
                except Exception as e: pass

            # 2. Quét list AUTO (Lặp lại)
            current_auto = list(user['auto_watching']) 
            for symbol in current_auto:
                try: 
                    if symbol in user['active_trades']: continue 

                    opens, highs, lows, closes, vols, _ = lay_data_binance(symbol)
                    if closes is not None:
                        inds = calculate_indicators(closes, highs, lows, vols)
                        tin_hieu, sl, tp, ly_do = kiem_tra_tin_hieu(opens, highs, lows, closes, vols, inds)
                        if tin_hieu:
                            execute_trade(chat_id, symbol, tin_hieu, ly_do, closes[-1], sl, tp, is_auto=True)
                except Exception as e: pass
            
            # 3. Quản lý lệnh đang chạy
            active_symbols = list(user['active_trades'].keys())
            for symbol in active_symbols:
                try:
                    trade = user['active_trades'][symbol]
                    _, _, _, closes, _, _ = lay_data_binance(symbol)
                    if closes is not None:
                        curr = closes[-1]
                        if trade['type'] == 'LONG':
                            hit_tp, hit_sl = curr >= trade['tp'], curr <= trade['sl']
                            move = (curr - trade['entry']) / trade['entry']
                        else: 
                            hit_tp, hit_sl = curr <= trade['tp'], curr >= trade['sl']
                            move = (trade['entry'] - curr) / trade['entry']
                        
                        if hit_tp or hit_sl:
                            pnl = move * trade['leverage'] * trade['amount']
                            user['balance'] += (trade['amount'] + pnl)
                            ket_qua = "WIN 🟢" if hit_tp else "LOSS 🔴"
                            if hit_tp: user['stats']['wins'] += 1
                            else: user['stats']['losses'] += 1
                            
                            is_auto_trade = trade.get('is_auto', False)
                            auto_msg = "\n🔄 Đang quét kèo mới tiếp..." if is_auto_trade else "\n🏁 Đã dừng theo dõi."

                            bot.send_message(chat_id, f"🔔 **KẾT THÚC {symbol}: {ket_qua}**\nLãi/Lỗ: {pnl:+,.0f} đ\n💰 Vốn mới: {user['balance']:,.0f} đ{auto_msg}", parse_mode="Markdown")
                            
                            del user['active_trades'][symbol]
                except: pass

            time.sleep(60) 
        except Exception as e:
            time.sleep(10)

# --- BOT COMMANDS ---
@bot.message_handler(commands=['start', 'help'])
def send_help(message):
    user = get_user_data(message.chat.id)
    help_text = (
        "📖 **HƯỚNG DẪN BOT PRICE ACTION (HARDCORE)** 📖\n\n"
        "🛠 **1. CÀI ĐẶT & VỐN:**\n"
        "   👉 `/Von [Số tiền]`: Cài tổng vốn (Ví dụ: `/Von 1000000`)\n"
        "   👉 `/Cuoc [Số tiền]`: Cài tiền đi lệnh (Ví dụ: `/Cuoc 50000`)\n"
        "   👉 `Xem von`: Kiểm tra số dư hiện tại.\n\n"
        "🧪 **2. BACKTEST (KIỂM TRA QUÁ KHỨ):**\n"
        "   👉 `Backtest [Coin] Von [Tiền]`: Test 7 ngày.\n"
        "      - VD: `Backtest BTC Von 500000`\n"
        "   👉 `Backtest 1 thang [Coin] Von [Tiền]`: Test 30 ngày.\n"
        "   ℹ️ *Bot sẽ hiện: Tổng lệnh Thắng/Thua, Tỷ lệ Win, Lãi/Lỗ cuối cùng.*\n\n"
        "🚀 **3. GIAO DỊCH (TRADE):**\n"
        "   👉 `Entry now [Coin]`: Vào lệnh NGAY LẬP TỨC.\n"
        "   👉 `Scan`: Quét 10 coin có tín hiệu đẹp.\n"
        "   👉 `Theo doi [Coin]`: Canh tín hiệu -> Vào lệnh -> Xong thì Dừng.\n"
        "      - VD: `Theo doi BTC SOL`\n"
        "   👉 `/Auto [Coin]`: Canh tín hiệu -> Vào lệnh -> Xong thì Lặp lại 24/7 (NEW 🔥).\n"
        "      - VD: `/Auto BTC ETH`\n\n"
        "📊 **4. TIỆN ÍCH KHÁC:**\n"
        "   👉 `Thong ke`: Xem tỷ lệ thắng/thua.\n"
        "   👉 `Xem theo doi`: Xem danh sách đang canh.\n"
        "   👉 `Dung`: Dừng tất cả (Cả Auto và Theo doi).\n"
        "   👉 Nhập tên Coin bất kỳ (VD: `PEPE`) để xem Chart.\n\n"
        "--------------------------\n"
        f"💰 Vốn: **{user['balance']:,.0f} đ**\n"
        f"💵 Cược: **{user['bet_amount']:,.0f} đ**"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['Auto', 'auto'])
def handle_auto(message):
    try:
        coins = message.text.replace("/Auto", "").replace("/auto", "").strip().upper().replace(",", " ").split()
        if not coins:
            bot.reply_to(message, "⚠️ Nhập tên coin. VD: `/Auto BTC ETH`")
            return
        
        chat_id = message.chat.id
        user = get_user_data(chat_id)
        
        added = []
        for c in coins:
            if c not in user['auto_watching']:
                user['auto_watching'].append(c)
                added.append(c)
                if c in user['watching']: user['watching'].remove(c)

        if added:
            bot.reply_to(message, f"🔄 Đã bật chế độ **AUTO 24/7** cho: {', '.join(added)}\n(Bot sẽ tự động tìm kèo mới sau khi chốt xong)", parse_mode="Markdown")
            threading.Thread(target=monitor_thread, args=(chat_id,)).start()
        else:
            bot.reply_to(message, "⚠️ Các coin này đã ở trong chế độ Auto rồi.")
    except Exception as e:
        bot.reply_to(message, f"Lỗi: {e}")

@bot.message_handler(func=lambda message: True)
def handle_msg(message):
    text = message.text.strip().upper()
    chat_id = message.chat.id
    user = get_user_data(chat_id)
    
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
            bot.reply_to(message, f"⏳ Đang Backtest {t_str} PA Scalping cho {symbol}...\n(Vốn giả định: {cap:,.0f}đ)")
            threading.Thread(target=process_backtest, args=(chat_id, symbol, cap, days)).start()
        except: pass
        return

    if text.startswith("ENTRY NOW"):
        symbol = text.replace("ENTRY NOW", "").replace("(", "").replace(")", "").strip()
        opens, highs, lows, closes, vols, _ = lay_data_binance(symbol)
        if closes is None: return
        inds = calculate_indicators(closes, highs, lows, vols)
        p_now = closes[-1]
        vwap = inds['vwap'][-1]
        if p_now > vwap:
            direc = "LONG 🟢 (Trend VWAP)"
            sl = min(lows[-1], vwap) * 0.998
            tp = p_now + (p_now - sl) * 1.5
        else:
            direc = "SHORT 🔴 (Trend VWAP)"
            sl = max(highs[-1], vwap) * 1.002
            tp = p_now - (sl - p_now) * 1.5
        execute_trade(chat_id, symbol, direc, "Lệnh Tay", p_now, sl, tp)
        threading.Thread(target=monitor_thread, args=(chat_id,)).start()
        return

    if text == "SCAN":
        res = scan_market(chat_id)
        if res: bot.reply_to(message, "🔍 **KÈO PRICE ACTION:**\n" + "\n".join(res))
        else: bot.reply_to(message, "Chưa có tín hiệu đẹp.")
        return
    if text.startswith("THEO DOI"):
        coins = text.replace("THEO DOI", "").replace(",", " ").split()
        valid = [c.strip().upper() for c in coins if c.strip()][:5]
        if valid:
            user['watching'] = valid
            for coin in valid:
                if coin in user['auto_watching']: user['auto_watching'].remove(coin)
            bot.reply_to(message, f"📡 Đang canh (1 lần): {', '.join(valid)}")
            threading.Thread(target=monitor_thread, args=(chat_id,)).start()
        return
    if text == "DUNG":
        user['watching'] = []
        user['auto_watching'] = [] 
        bot.reply_to(message, "🛑 Đã dừng tất cả (Auto & Theo dõi).")
        return
    if text in ["THONG KE", "THỐNG KÊ"]:
        w, l = user['stats']['wins'], user['stats']['losses']
        rate = w/(w+l)*100 if (w+l)>0 else 0
        bot.reply_to(message, f"📊 Win: {w} | Loss: {l} ({rate:.1f}%)")
        return
    if text in ["XEM THEO DOI", "LIST"]:
        msg = ""
        if user['watching']: msg += f"📋 Theo dõi (1 lần): {', '.join(user['watching'])}\n"
        if user['auto_watching']: msg += f"🔄 Auto (24/7): {', '.join(user['auto_watching'])}"
        if not msg: msg = "📭 Trống."
        bot.reply_to(message, msg)
        return

    symbol = text.split()[0]
    msg = bot.reply_to(message, f"🔍 Check {symbol}...")
    ty = lay_ty_gia_remitano()
    if ty: 
        global TY_GIA_USDT_CACHE
        TY_GIA_USDT_CACHE = ty
    opens, highs, lows, closes, vols, src = lay_data_binance(symbol)
    if closes is not None:
        inds = calculate_indicators(closes, highs, lows, vols)
        photo = ve_chart(symbol, closes, inds)
        tin_hieu, _, _, ly_do = kiem_tra_tin_hieu(opens, highs, lows, closes, vols, inds)
        status = f"🚀 **{tin_hieu}**" if tin_hieu else "Chờ tín hiệu."
        if ly_do: status += f"\n({ly_do})"
        gia_vnd = closes[-1] * TY_GIA_USDT_CACHE
        caption = f"📊 **{symbol} (1m PA)**\n🇺🇸 ${closes[-1]:,.4f}\n🇻🇳 {gia_vnd:,.0f} đ\nStatus: {status}\n📡 {src}"
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

print("🤖 BOT SIGNAL ĐANG CHẠY (HARDCORE MODE)...")
keep_alive()
bot.infinity_polling()

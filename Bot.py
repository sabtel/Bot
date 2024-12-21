
import ccxt
import pandas as pd
import matplotlib.pyplot as plt
from ta.trend import MACD, EMAIndicator
from ta.momentum import RSIIndicator
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext

# Initialize exchange
exchange = ccxt.binance()
symbol = "BTC/USDT"  # Trading pair
timeframe = "5m"     # Smallest timeframe for more signals
limit = 100          # Number of candles to fetch

def fetch_data_with_retry(symbol, timeframe, limit, retries=5, delay=5):
    """Fetch OHLCV data with retries."""
    for attempt in range(retries):
        try:
            print(f"Attempt {attempt + 1} to fetch data...")
            data = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            print("Data fetched successfully!")
            return pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        except Exception as e:
            print(f"Error: {e}")
            if attempt < retries - 1:
                time.sleep(delay * (2 ** attempt))  # Exponential backoff
            else:
                print("Max retries exceeded. Check your internet connection or Binance API status.")
                raise

def calculate_indicators(df):
    """Calculate MACD, RSI, EMA indicators."""
    # MACD
    macd = MACD(df['close'])
    df['macd'] = macd.macd()
    df['signal'] = macd.macd_signal()
    df['macd_histogram'] = macd.macd_diff()

    # RSI
    rsi = RSIIndicator(df['close'])
    df['rsi'] = rsi.rsi()
    
    # Exponential Moving Averages (very short periods)
    df['ema_short'] = EMAIndicator(df['close'], window=3).ema_indicator()
    df['ema_long'] = EMAIndicator(df['close'], window=6).ema_indicator()

    return df

def generate_signals(df):
    """Generate buy and sell signals with overlap resolution."""
    # MACD Crossovers
    df['macd_crossover'] = df['macd'] > df['signal']
    df['macd_crossunder'] = df['macd'] < df['signal']

    # Relaxed RSI thresholds
    df['rsi_rising'] = df['rsi'] > 40  # Buy when RSI > 40
    df['rsi_falling'] = df['rsi'] < 60  # Sell when RSI < 60

    # Minor price movements
    df['price_increasing'] = df['close'] > df['close'].shift(1)
    df['price_decreasing'] = df['close'] < df['close'].shift(1)

    # EMA crossovers
    df['ema_crossover'] = df['ema_short'] > df['ema_long']
    df['ema_crossunder'] = df['ema_short'] < df['ema_long']

    # Raw signals
    df['raw_buy_signal'] = (df['macd_crossover'] | df['price_increasing'] | df['ema_crossover']) & (df['rsi_rising'])
    df['raw_sell_signal'] = (df['macd_crossunder'] | df['price_decreasing'] | df['ema_crossunder']) & (df['rsi_falling'])

    # Scoring signals
    df['buy_score'] = (
        (df['macd_histogram'] > 0).astype(int) * 2 +  # Strong positive MACD histogram
        (df['rsi'] - 50) * 0.1 +                    # RSI value
        (df['ema_short'] > df['ema_long']).astype(int)  # EMA crossover
    )
    df['sell_score'] = (
        (df['macd_histogram'] < 0).astype(int) * 2 +  # Strong negative MACD histogram
        (50 - df['rsi']) * 0.1 +                    # RSI value
        (df['ema_short'] < df['ema_long']).astype(int)  # EMA crossunder
    )

    # Resolve overlaps
    df['buy_signal'] = (df['raw_buy_signal'] & (df['buy_score'] > df['sell_score'])).astype(bool)
    df['sell_signal'] = (df['raw_sell_signal'] & (df['sell_score'] > df['buy_score'])).astype(bool)

    return df

def plot_signals(df, update: Update):
    """Plot buy and sell signals and send it to the user."""
    plt.figure(figsize=(14, 8))

    # Price chart
    plt.subplot(2, 1, 1)
    plt.plot(df['timestamp'], df['close'], label='Close Price', color='blue')
    plt.scatter(df['timestamp'][df['buy_signal']], df['close'][df['buy_signal']], label='Buy Signal', marker='^', color='green', alpha=0.7)
    plt.scatter(df['timestamp'][df['sell_signal']], df['close'][df['sell_signal']], label='Sell Signal', marker='v', color='red', alpha=0.7)
    plt.title(f'{symbol} Price with Buy/Sell Signals')
    plt.xlabel('Timestamp')
    plt.ylabel('Price (USDT)')
    plt.legend()
# MACD Chart
    plt.subplot(2, 1, 2)
    plt.plot(df['timestamp'], df['macd'], label='MACD', color='purple')
    plt.plot(df['timestamp'], df['signal'], label='Signal Line', color='orange')
    plt.axhline(0, linestyle='--', color='black', linewidth=1)
    plt.title('MACD Indicator')
    plt.xlabel('Timestamp')
    plt.legend()

    plt.tight_layout()

    # Save the plot to a file
    plt.savefig('signals_plot.png')

    # Send the plot to the user on Telegram
    update.message.reply_photo(photo=open('signals_plot.png', 'rb'))

async def start(update: Update, context: CallbackContext):
    """Handle /start command."""
    await update.message.reply_text("Hello! at the end of your timedesk use this bot. Use /signals to get the latest signals.")

async def signals(update: Update, context: CallbackContext):
    """Handle /signals command."""
    try:
        # Fetch data
        df = fetch_data_with_retry(symbol, timeframe, limit)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        # Calculate indicators and generate signals
        df = calculate_indicators(df)
        df = generate_signals(df)

        # Display recent data with signals
        recent_data = df[['timestamp', 'close', 'buy_score', 'sell_score', 'buy_signal', 'sell_signal']].tail(20)
        signal_message = "Recent Signals:\n\n"
        for index, row in recent_data.iterrows():
            signal_message += f"Time: {row['timestamp']}, Close: {row['close']}, Buy: {row['buy_signal']}, Sell: {row['sell_signal']}\n"

        await update.message.reply_text(signal_message)

        # Plot and send to user
        plot_signals(df, update)

    except Exception as e:
        await update.message.reply_text(f"An error occurred: {e}")

def main():
    # Set up the bot with your token
    application = Application.builder().token("7797137480:AAEnTiM6oSaMk_lRpFrJqQMKVnggwVGAs2w").build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("signals", signals))

    # Start the bot
    application.run_polling()

if __name__ == "main":
    main()

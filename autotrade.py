import os
from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI
import pyupbit
import schedule
import time
import json
import pandas as pd
import pandas_ta as ta

#set Up 
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
upbit = pyupbit.Upbit(os.getenv("UPBIT_ACCESS_KEY"), os.getenv("UPBIT_SECRET_KEY"))


def get_instructions(file_path): #Instruction 파일을 읽는 함수 
    try:
        with open(file_path, "r",encoding="utf-8") as file:
                instructions = file.read()
        return instructions


    except FileNotFoundError:
        print(f"No instructions found at {file_path}")
    except Exception as e:
        print(f"Error in reading instructions: {e}")



def analyze_data_with_gpt4(data_json):
    instructions_path = "instructions.md"
    try:
        instructions = get_instructions(instructions_path)
        if not instructions:
            print("No instructions found.")
            return None

        current_status = get_current_status()
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": data_json},
                {"role": "user", "content": current_status}
            ],
            response_format={"type":"json_object"}
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error in analyzing data with GPT-4: {e}")
        return None


def get_current_status():
    orderbook = pyupbit.get_orderbook("KRW-BTC")
    current_time = orderbook['timestamp']
    btc_balance = 0
    krw_balance = 0
    btc_avg_buy_price = 0 
    balances = upbit.get_balances()
    for balance in balances:
        if balance['currency'] == "BTC":
            btc_balance = balance['balance']
            btc_avg_buy_price = balance['avg_buy_price']
        if balance['currency'] == "KRW":
            krw_balance = balance['balance']

    current_status = {'current_time' : current_time,'orderbook':orderbook,'btc_balance':btc_balance,'krw_balance':krw_balance,'btc_avg_buy_price':btc_avg_buy_price}
    return json.dumps(current_status)

def fetch_and_prepare_data():
    df_daily = pyupbit.get_ohlcv("KRW-BTC","day",count=30)
    df_hourly = pyupbit.get_ohlcv("KRW-BTC",interval="minute60",count=24)

    def add_indicators(df):
        df['SMA_10'] = ta.sma(df['close'],length=10)
        df['EMA_10'] = ta.ema(df['close'],length=10)

        #RSI
        df['RSI_14'] = ta.rsi(df['close'],length = 14)

        #Stochastic Oscillator
        stoch = ta.stoch(df['high'],df['low'],df['close'],k=14,d=3,smooth_k =3)
        df = df.join(stoch)

        #MACD
        ema_fast = df['close'].ewm(span=12,adjust=False).mean()
        ema_slow = df['close'].ewm(span=26,adjust=False).mean()
        macd = ema_fast - ema_slow
        df['MACD'] = ema_fast - ema_slow
        df['Signal_Line'] = df['MACD'].ewm(span=9,adjust=False).mean()
        df['MACD_Histogram'] = df['MACD'] - df['Signal_Line']

        #Bollinger Bands
        df['Middle_Band'] = df['close'].rolling(window=20).mean()
        std_dev = df['close'].rolling(window=20).std()
        df['Upper_Band'] = df['Middle_Band'] + (std_dev * 2)
        df['Lower_Band'] = df['Middle_Band'] - (std_dev * 2)

        return df
    
    df_daily = add_indicators(df_daily)
    df_hourly = add_indicators(df_hourly)

    combined_df = pd.concat([df_daily,df_hourly],keys=['daily','hourly'])
    combined_data = combined_df.to_json(orient='split')
    print(len(combined_data))

    return json.dumps(combined_data)


def execute_buy():
    print("Attempting to but BTC")
    try: 
        krw = upbit.get_balance("KRW")
        if krw > 5000:
            result = upbit.buy_market_order("KRW-BTC",krw*0.9995)
            print(result)
    except Exception as e: 
        print(f"Failed to buy BTC: {e}")

def execute_sell():
    print("Attempting to sell BTC")
    try: 
        btc = upbit.get_balance("BTC")
        current_price = pyupbit.get_orderbook(ticker="KRW-BTC")['orderbook_units'][0]['ask_price']
        if current_price*btc > 5000:
            result = upbit.sell_market_order("KRW-BTC",btc*0.9995)
            print("Sell order Successful",result)
    except Exception as e: 
        print(f"Failed to sell BTC: {e}")

def make_decision_and_execute():
    print("판단하고 결정하는중..")
    data_json = fetch_and_prepare_data()
    advice = analyze_data_with_gpt4(data_json)

    try:
        decision = json.loads(advice)
        # print(decision)
        if decision.get('decision') == "buy":
            print(f"구매하세요 이유는 : {decision.get('reason')}")
            execute_buy()

        elif decision.get('decision') == "sell":
            print(f"지금 파세요 이유는: {decision.get('reason')}")
            execute_sell()

        elif decision.get('decision') == "hold":
            print(f"아직 기다리세요 이유는 : {decision.get('reason')}")
    except Exception as e:
        print(f"Failed to parse advice as JSON: {e}")



if __name__ == "__main__":
    make_decision_and_execute()
    schedule.every().hour.at(":01").do(make_decision_and_execute)

    while True:
        schedule.run_pending()
        time.sleep(1)


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Dec 13 17:34:43 2021

@author: mikhil
"""


import numpy as np
import pandas as pd
from stocktrends import Renko
import statsmodels.api as sm
import copy
import requests 
import yfinance as yf 
import copy
import datetime as dt
import time 
from sys import exit 
import requests
from bs4 import BeautifulSoup


def MACD(DF,a,b,c):
    """function to calculate MACD
       typical values a = 12; b =26, c =9"""
    df = DF.copy()
    df["MA_Fast"]=df["Adj Close"].ewm(span=a,min_periods=a).mean()
    df["MA_Slow"]=df["Adj Close"].ewm(span=b,min_periods=b).mean()
    df["MACD"]=df["MA_Fast"]-df["MA_Slow"]
    df["Signal"]=df["MACD"].ewm(span=c,min_periods=c).mean()
    df.dropna(inplace=True)
    return (df["MACD"],df["Signal"])

def ATR(DF,n):
    "function to calculate True Range and Average True Range"
    df = DF.copy()
    df['H-L']=abs(df['High']-df['Low'])
    df['H-PC']=abs(df['High']-df['Adj Close'].shift(1))
    df['L-PC']=abs(df['Low']-df['Adj Close'].shift(1))
    df['TR']=df[['H-L','H-PC','L-PC']].max(axis=1,skipna=False)
    #df['ATR'] = df['TR'].rolling(n).mean()
    df['ATR'] = df['TR'].ewm(span=n,adjust=False,min_periods=n).mean()
    df2 = df.drop(['H-L','H-PC','L-PC'],axis=1)
    return df2

def slope(ser,n):
    "function to calculate the slope of n consecutive points on a plot"
    slopes = [i*0 for i in range(n-1)]
    for i in range(n,len(ser)+1):
        y = ser[i-n:i]
        x = np.array(range(n))
        y_scaled = (y - y.min())/(y.max() - y.min())
        x_scaled = (x - x.min())/(x.max() - x.min())
        x_scaled = sm.add_constant(x_scaled)
        model = sm.OLS(y_scaled,x_scaled)
        results = model.fit()
        slopes.append(results.params[-1])
    slope_angle = (np.rad2deg(np.arctan(np.array(slopes))))
    return np.array(slope_angle)

def renko_DF(DF):
    "function to convert ohlc data into renko bricks"
    df = DF.copy()
    df.reset_index(inplace=True)
    df = df.iloc[:,[0,1,2,3,4,5]]
    df.columns = ["date","open","high","low","close","volume"]
    df2 = Renko(df)
    df2.brick_size = max(0.5,round(ATR(DF,120)["ATR"][-1],0))
    renko_df = df2.get_ohlc_data()
    renko_df["bar_num"] = np.where(renko_df["uptrend"]==True,1,np.where(renko_df["uptrend"]==False,-1,0))
    for i in range(1,len(renko_df["bar_num"])):
        if renko_df["bar_num"][i]>0 and renko_df["bar_num"][i-1]>0:
            renko_df["bar_num"][i]+=renko_df["bar_num"][i-1]
        elif renko_df["bar_num"][i]<0 and renko_df["bar_num"][i-1]<0:
            renko_df["bar_num"][i]+=renko_df["bar_num"][i-1]
    renko_df.drop_duplicates(subset="date",keep="last",inplace=True)
    return renko_df



''' retrieve top 5 best performing stocks from tradingview.com'''

tickers = []
url = 'https://www.tradingview.com/markets/stocks-usa/market-movers-best-performing/'
headers={'User-Agent': "Mozilla/5.0"}
page = requests.get(url, headers=headers)
page_content = page.content
soup = BeautifulSoup(page_content,'html.parser')
rows = soup.findAll("tr", attrs = {'class':'tv-data-table__row tv-data-table__stroke tv-screener-table__result-row'}) # try to remove the leading space if the code breaks "class": "W(100%) Bdcl(c)"

for row in rows:
    divs = row.findAll('a')   
    tickers.append(divs[0].text)
    
for x in range(len(tickers)):
   tickers[x] = tickers[x].replace('.', '-')
stocks = tickers[0:5]


'''connectng to interactive brokers  gateway'''

from ib_insync import *
util.startLoop()  # uncomment this line when in a notebook
ib = IB()
ib.connect('127.0.0.1', 7496, clientId=1)


buy_order = MarketOrder('BUY', 10)
sell_order = MarketOrder('SELL', 10)


#seting some parametres

order = {}
contract={}
tickers_signal = {}
tickers_ret = {}
original = {}


for ticker in stocks:
    tickers_signal[ticker] = ""
    original[ticker] = 0
    contract[ticker]= Stock(ticker, "SMART", "USD")
    tickers_ret[ticker] = 0
 


#taking note of any exisiting long term positions to not be included in day trading     
currpositions = ib.positions()
for position in currpositions: 
    contract_current = position.contract
    original[contract_current.symbol] = position.position


#function to send alert to telegram bot
def send(text):
	token = 'your token'
	params = {'chat_id': 'your chatbot id', 'text': text, 'parse_mode': 'HTML'}
	resp = requests.post('https://api.telegram.org/bot{}/sendMessage'.format(token), params)
	resp.raise_for_status()
    
#calculate returns
def returns(fill):
    price = fill.execution.avgPrice
    if (fill.execution.side == "BOT"):
        price = price *-1
    tickers_ret[fill.contract.symbol]= tickers_ret[fill.contract.symbol] + fill.execution.avgPrice
    return tickers_ret[fill.contract.symbol]


def order_status(trade):
    if trade.orderStatus.status == 'Filled':
        fill = trade.fills[-1]
        text = f'{fill.time} - {fill.execution.side} {fill.contract.symbol} {fill.execution.shares} @ {fill.execution.avgPrice}'
        send(text) 
        pl = returns(fill)
        send ('p/l for' + fill.contract.symbol + str(pl))



def main():    
    
    ohlc_intraday = {} 
    ohlc_renko = {}
    
    for ticker in stocks:
        
        
        start = dt.datetime.today()-dt.timedelta(10)
        end = dt.datetime.today()
        
        try:
            #retrieve data using yfinance
            temp = yf.download(ticker, start,end, interval = "5m") #5min interval data from the past 10 days
            ohlc_intraday[ticker] = temp
            
        except: 
            #retrieve data using alpha vantage
            api_key = 'your api_key'
            api_url = f'https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol={ticker}&market=USD&interval=5min&outputsize=full&apikey={api_key}'
            
            
            raw_df = requests.get(api_url).json()
               
            df = pd.DataFrame(raw_df[f'Time Series (5min)']).T
            df = df.rename(columns = {'1. open': 'Open', '2. high': 'High', '3. low': 'Low', '4. close': 'Close', '5. volume': 'Volume'})
            for i in df.columns:
                df[i] = df[i].astype(float)
            df.index = pd.to_datetime(df.index)
            df = df.iloc[::-1]
            ohlc_intraday = copy.deepcopy(df)
        
    df = copy.deepcopy(ohlc_intraday)
    for ticker in stocks:
        print("merging for ",ticker)
        renko = renko_DF(df[ticker])
        renko.columns = ["Date","open","high","low","close","uptrend","bar_num"]
        df[ticker]["Date"] = df[ticker].index
        ohlc_renko[ticker] = df[ticker].merge(renko.loc[:,["Date","bar_num"]],how="outer",on="Date")
        ohlc_renko[ticker].set_index("Date", inplace = True)
        ohlc_renko[ticker]["bar_num"].fillna(method='ffill',inplace=True)
        ohlc_renko[ticker]["macd"]= MACD(ohlc_renko[ticker],12,26,9)[0]
        ohlc_renko[ticker]["macd_sig"]= MACD(ohlc_renko[ticker],12,26,9)[1]
        ohlc_renko[ticker]["macd_slope"] = slope(ohlc_renko[ticker]["macd"],5)
        ohlc_renko[ticker]["macd_sig_slope"] = slope(ohlc_renko[ticker]["macd_sig"],5)
        

    #Identifying signals and excuting orders
    for ticker in stocks:
        
        if tickers_signal[ticker] == "":
            if ohlc_renko[ticker]["bar_num"][-1]>= 1:
                tickers_signal[ticker] = "Buy"
                trade = ib.placeOrder(contract[ticker], buy_order)
                trade.filledEvent+= order_status
                
        elif tickers_signal[ticker] == "Buy":
           
            if ohlc_renko[ticker]["bar_num"][-1]<1 and (ohlc_renko[ticker]["macd"][-1]<ohlc_renko[ticker]["macd_sig"][-1] and ohlc_renko[ticker]["macd_slope"][-1]<ohlc_renko[ticker]["macd_sig_slope"][-1]):
                tickers_signal[ticker] = ""
                trade = ib.placeOrder(contract[ticker], sell_order)
                trade.filledEvent+= order_status





text = "SCRIPT STARTED"
send(text)

starttime=time.time()
timeout = time.time() + 390*60  # 60 seconds times 390 meaning the script will run for 6.5hours

while time.time() <= timeout:
    try:
        print("passthrough at ",time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
        main()
        ib.sleep(300 - ((time.time() - starttime) % 300)) #script will run every 5 minutes
     
        
    except Exception as e:
        send(e)
        send("SCRIPT RECONNECTING")
        time.sleep(120)
        try:
            ib.connect('127.0.0.1', 7496, clientId=4)
            send("CONNECTED")
        except:
            text = 0
            for key in tickers_ret:
                text = text + tickers_ret[key] 
                send("Overall p/l:"+str(text))

            ib.disconnect()
            text = "unsuccessful running for script"
            send(text)
            exit()
            
if(ib.isConnected()):
    positions = ib.positions()
    for position in positions:
        contract_current = position.contract
        if position.position > original[contract_current.symbol]:
            trade = ib.placeOrder(contract, sell_order)
            trade.filledEvent+= order_status

    
    ib.disconnect()
    text = "successful running for script"
    send(text)

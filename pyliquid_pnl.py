# -*- coding:utf-8 -*-

import os
import traceback
import requests
import pandas as pd
from dateutil import parser
from logging import getLogger, Formatter, FileHandler, StreamHandler, DEBUG
from pytz import timezone
from datetime import datetime, timedelta
from time import sleep
import sqlite3
import sys
args = sys.argv
if args[1] == 'send_discord':
    import matplotlib
    matplotlib.use('Agg')
from matplotlib import pyplot as plt
import os
from pandas.plotting import register_matplotlib_converters
register_matplotlib_converters()

import pyliquid
import config



logger = getLogger(name="collateral")
logger.setLevel(DEBUG)
handler1 = StreamHandler()
handler1.setFormatter(Formatter("%(asctime)s %(levelname)8s %(message)s"))
handler2 = FileHandler(filename="collateral.log")  # handler2はファイル出力
handler2.setFormatter(Formatter("%(asctime)s %(levelname)8s %(message)s"))
logger.addHandler(handler1)
logger.addHandler(handler2)


class CollateralSaver(object):

    def __init__(self, key, secret, file_dir,
                 funding_currencies={'JPY': True, 'BTC': False, 'ETH': False,
                 'USD': False, 'QASH': False}):
        self.funding_currencies = funding_currencies
        self.data_dir = file_dir
        if not os.path.exists(file_dir + "/data"):
            os.mkdir(file_dir + "/data")
        self.db_path = file_dir + "/data/collateral.db"
        self.conn = sqlite3.connect(self.db_path)
        self.cur = self.conn.cursor()
        self.create_collateral_table()
        self.api = pyliquid.API(key, secret)

    def __del__(self):
        self.conn.close()

    def create_collateral_table(self):
        create_table = '''CREATE TABLE IF NOT EXISTS collateral (date text, open_pnl real, total_unrealized_margin real, total_margin real)'''
        self.cur.execute(create_table)
        self.conn.commit()

    def save(self):
        try:
            date, open_pnl, total_unrealized_margin, total_margin = self.get_collateral()
        except:
            logger.debug(traceback.format_exc())
        self.save_to_sql(date, open_pnl, total_unrealized_margin, total_margin)
        logger.info('Saved Collateral.')

    def save_to_sql(self, date, open_pnl, total_unrealized_margin, total_margin):
        t = (date, open_pnl, total_unrealized_margin, total_margin)
        sql = 'INSERT INTO collateral (date, open_pnl, total_unrealized_margin, total_margin) VALUES(?,?,?,?)'
        self.cur.execute(sql, t)
        self.conn.commit()

    def get_collateral(self):
        date = datetime.now().astimezone(timezone('Asia/Tokyo'))
        accounts = self.api.get_trading_accounts()
        float_none = lambda x: float(0) if x is None else float(x)
        int_none = lambda x: int(0) if x is None else int(x)
        present_prices = {p['currency_pair_code']: float_none(p['last_traded_price']) for p in self.api.get_products() if int_none(p["volume_24h"] != 0)}
        open_pnl = 0
        margin = 0
        free_margin = 0
        for a in accounts:
            if a['funding_currency'] not in self.funding_currencies:
                continue
            if self.funding_currencies[a['funding_currency']]:
                if a['funding_currency'] == 'JPY':
                    present_price = 1
                else:
                    present_price = present_prices[a['funding_currency']+'JPY']
                open_pnl += float(a['pnl']) * present_price
                margin += float(a['margin']) * present_price
                free_margin += float(a['free_margin']) * present_price
        total_unrealized_margin = margin + free_margin
        total_margin = margin + free_margin - open_pnl
        return date, open_pnl, total_unrealized_margin, total_margin

    def describe_continually(self, interval):
        today = datetime.now().date() - timedelta(days=3)
        while True:
            logger.info('Redescribing.')
            df = self.get_df_from_db(start_dt=timezone('Asia/Tokyo').localize(
                datetime(year=today.year, month=today.month, day=today.day, hour=0, minute=0)))
            pl_now = self.describe_graph(df)
            logger.info(f'PL now: {pl_now}')
            plt.pause(interval)
            plt.clf()

    def describe_graph(self, data_df, open_position=True):
        plt.title("The capital curve")
        plt.xlabel("Date")
        plt.ylabel("PL(JPY)")
        if open_position:
            ax0 = plt.subplot(211)
            ax0.plot(data_df.index, data_df['total_unrealized_margin'] - data_df['total_unrealized_margin']
                    [0], color='r', label='total_unrealized_pnl')
            ax0.plot(data_df.index, data_df['total_margin'] -
                    data_df['total_margin'][0], color='b', label='total_realized_pnl')
            ax0.legend()
            ax1 = ax0.twinx()
            ax1.plot(data_df.index, data_df['open_pnl'], color='y', label='open_position_pnl')
            ax1.legend()
        else:
            ax0 = plt.subplot(111)
            ax0.plot(data_df.index, data_df['total_unrealized_margin'] - data_df['total_realized_margin']
                     [0], color='r', label='total_unrealized_pnl')
            ax0.plot(data_df.index, data_df['total_margin'] -
                     data_df['total_margin'][0], color='b', label='total_realized_pnl')
            ax0.legend()
        return data_df['total_unrealized_margin'][-1] - data_df['total_unrealized_margin'][0]

    def get_df_from_db(self, start_dt=None, end_dt=None):
        df = pd.read_sql("SELECT * FROM collateral", self.conn,
                         index_col="date", parse_dates=True)
        df.index = df.index.map(parser.parse)
        # 両方Noneの場合，全てのデータを描画
        if start_dt == None and end_dt == None:
            pass
        # startだけNoneの場合，endまでの資産曲線を全て描画．
        elif start_dt == None and end_dt != None:
            df = df[df.index <= end_dt]
        # endだけNone
        elif start_dt != None and end_dt == None:
            df = df[df.index >= start_dt]
        # 両方とも指定があるとき
        else:
            df = df[(df.index >= start_dt) & (df.index <= end_dt)]
        return df

    def save_graph(self, since=None):
        fig = plt.figure(figsize=(16, 8))
        data_df = self.get_df_from_db(start_dt=since)
        pl_now = self.describe_graph(data_df)
        logger.info(f'PLNow: {pl_now}')
        path = self.data_dir + '/collateral_report.png'
        plt.savefig(path)
        plt.close()
        return path, pl_now

    def send_to_discord(self, WEBHOOK_URL, since):
        path, pl_now = self.save_graph(since=since)
        payload = {'file': (path, open(path, 'rb'), "image/png")}
        requests.post(WEBHOOK_URL, files=payload)
        return


if __name__ == '__main__':
    WEBHOOK_URL = config.WEBHOOK_URL
    funding_currencies = config.funding_currencies
    key = config.KEY
    secret = config.SECRET
    file_dir = os.path.dirname(os.path.abspath(__file__))
    saver = CollateralSaver(key, secret, file_dir, funding_currencies=funding_currencies)
    today = datetime.now().date()
    TODAY = timezone('Asia/Tokyo').localize(
        datetime(year=today.year, month=today.month, day=today.day, hour=0, minute=0))
    if args[1] == 'save':
       saver.save()
    if args[1] == 'realtime_describe':
        saver.describe_continually(30)
    if args[1] == 'send_discord':
        saver.send_to_discord(WEBHOOK_URL, since=TODAY)
    if args[1] == 'today':
        fig = plt.figure(figsize=(16, 8))
        data_df = saver.get_df_from_db(start_dt=TODAY)
        pl_now = saver.describe_graph(data_df)
        print(f'PL Now: {pl_now}')
        plt.show()


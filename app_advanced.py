"""
Stock Prediction Lab v2.0 - Advanced Analysis Engine
Flask server with comprehensive market analysis following the advanced prediction strategy.
Includes: FII/DII data, CPR levels, OI analysis, VWAP, Gann levels, and multi-factor prediction.
"""

import nselib
from nselib import derivatives
from nselib import capital_market
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_from_directory
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS
import traceback
import os
import requests
import math
import json
import time


# Custom JSON encoder to handle numpy types
class NumpyJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        return super().default(obj)


app = Flask(__name__)
app.json = NumpyJSONProvider(app)
CORS(app)

# Global cache for Today's Picks
picks_cache = None
cache_timestamp = None
CACHE_DURATION = 300  # 5 minutes


# ============ UTILITY FUNCTIONS ============

def _clean_numeric(value):
    """Convert string values with commas to float."""
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(',', '').strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


def _get_previous_trading_date():
    """Get the previous trading day (skip weekends)."""
    today = datetime.now()
    prev = today - timedelta(days=1)
    # Skip weekends
    while prev.weekday() >= 5:  # 5=Saturday, 6=Sunday
        prev -= timedelta(days=1)
    return prev.strftime('%d-%m-%Y')


def _get_date_str(days_ago=0):
    """Get date string in DD-MM-YYYY format."""
    date = datetime.now() - timedelta(days=days_ago)
    while date.weekday() >= 5:
        date -= timedelta(days=1)
    return date.strftime('%d-%m-%Y')


def fetch_option_chain_with_retry(symbol, retries=3, backoff_seconds=1.2):
    """Fetch option chain with a few retries to mitigate transient SSL/network issues."""
    last_error = None
    for attempt in range(retries):
        try:
            df = derivatives.nse_live_option_chain(symbol)
            if df is not None and not df.empty:
                return df, None
            last_error = "Empty option chain response"
        except Exception as exc:  # noqa: BLE001 - we want the exact message for user context
            last_error = str(exc)
        time.sleep(backoff_seconds)
    return None, last_error


# ============ PHASE 1: MACRO-PRUDENTIAL CALIBRATION ============

def get_fii_dii_data():
    """
    Fetch FII/DII trading data and derivatives statistics.
    This helps determine institutional bias.
    """
    result = {
        "success": False,
        "error": None,
        "data": {}
    }
    
    try:
        prev_date = _get_previous_trading_date()
        
        # Get FII derivatives statistics
        fii_stats = derivatives.fii_derivatives_statistics(prev_date)
        
        # Get participant-wise open interest
        participant_oi = derivatives.participant_wise_open_interest(prev_date)
        
        # Parse FII data
        fii_data = {}
        for _, row in fii_stats.iterrows():
            instrument = row['fii_derivatives']
            fii_data[instrument] = {
                "buy_contracts": _clean_numeric(row['buy_contracts']),
                "sell_contracts": _clean_numeric(row['sell_contracts']),
                "buy_value_cr": _clean_numeric(row['buy_value_in_Cr']),
                "sell_value_cr": _clean_numeric(row['sell_value_in_Cr']),
                "open_contracts": _clean_numeric(row['open_contracts']),
                "open_value_cr": _clean_numeric(row['open_contracts_value_in_Cr'])
            }
        
        # Calculate net FII position in Index Futures
        index_futures_buy = fii_data.get('Index Futures', {}).get('buy_value_cr', 0)
        index_futures_sell = fii_data.get('Index Futures', {}).get('sell_value_cr', 0)
        net_index_futures = index_futures_buy - index_futures_sell
        
        # Stock Futures net
        stock_futures_buy = fii_data.get('Stock Futures', {}).get('buy_value_cr', 0)
        stock_futures_sell = fii_data.get('Stock Futures', {}).get('sell_value_cr', 0)
        net_stock_futures = stock_futures_buy - stock_futures_sell
        
        # Index Options net
        index_options_buy = fii_data.get('Index Options', {}).get('buy_value_cr', 0)
        index_options_sell = fii_data.get('Index Options', {}).get('sell_value_cr', 0)
        net_index_options = index_options_buy - index_options_sell
        
        # Parse participant OI for Long/Short ratio
        fii_row = None
        for idx, row in participant_oi.iterrows():
            if 'FII' in str(row.get('Client Type', '')):
                fii_row = row
                break
        
        if fii_row is not None:
            fii_index_long = _clean_numeric(fii_row.get('Future Index Long', 0))
            fii_index_short = _clean_numeric(fii_row.get('Future Index Short', 0))
            total_fii_index = fii_index_long + fii_index_short
            fii_long_ratio = (fii_index_long / total_fii_index * 100) if total_fii_index > 0 else 50
        else:
            fii_index_long = 0
            fii_index_short = 0
            fii_long_ratio = 50
        
        # Determine FII bias
        fii_bias = "NEUTRAL"
        fii_signal = ""
        
        if fii_long_ratio > 70:
            fii_bias = "OVERBOUGHT"
            fii_signal = "Market overbought - FII Longs >70%. Expect correction/dip."
        elif fii_long_ratio < 30:
            fii_bias = "OVERSOLD"
            fii_signal = "Market oversold - FII Longs <30%. Expect bounce."
        elif net_index_futures > 500:
            fii_bias = "BULLISH"
            fii_signal = "FIIs net buyers in Index Futures. Bullish bias."
        elif net_index_futures < -500:
            fii_bias = "BEARISH"
            fii_signal = "FIIs net sellers in Index Futures. Bearish bias."
        else:
            fii_signal = "FII activity neutral. Watch other indicators."
        
        result["success"] = True
        result["data"] = {
            "date": prev_date,
            "fii_index_futures_net": round(net_index_futures, 2),
            "fii_stock_futures_net": round(net_stock_futures, 2),
            "fii_index_options_net": round(net_index_options, 2),
            "fii_index_long": fii_index_long,
            "fii_index_short": fii_index_short,
            "fii_long_ratio": round(fii_long_ratio, 2),
            "fii_bias": fii_bias,
            "fii_signal": fii_signal,
            "fii_details": fii_data
        }
        
    except Exception as e:
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
    
    return result


def get_market_overview():
    """
    Get Nifty 50 data for market overview and CPR calculation.
    """
    result = {
        "success": False,
        "error": None,
        "data": {}
    }
    
    try:
        # Get Nifty 50 index data
        nifty_data = capital_market.index_data('NIFTY 50', period='1M')
        
        if nifty_data.empty:
            result["error"] = "No Nifty data available"
            return result
        
        # Get latest and previous day data
        latest = nifty_data.iloc[-1]
        previous = nifty_data.iloc[-2] if len(nifty_data) > 1 else latest
        
        # Current values
        nifty_open = _clean_numeric(latest['OPEN_INDEX_VAL'])
        nifty_high = _clean_numeric(latest['HIGH_INDEX_VAL'])
        nifty_low = _clean_numeric(latest['LOW_INDEX_VAL'])
        nifty_close = _clean_numeric(latest['CLOSE_INDEX_VAL'])
        
        # Previous day values for CPR
        prev_high = _clean_numeric(previous['HIGH_INDEX_VAL'])
        prev_low = _clean_numeric(previous['LOW_INDEX_VAL'])
        prev_close = _clean_numeric(previous['CLOSE_INDEX_VAL'])
        
        # Calculate CPR (Central Pivot Range)
        pivot = (prev_high + prev_low + prev_close) / 3
        bc = (prev_high + prev_low) / 2  # Bottom CPR
        tc = (pivot - bc) + pivot  # Top CPR
        
        # CPR width analysis
        cpr_width = abs(tc - bc)
        cpr_width_percent = (cpr_width / prev_close) * 100
        
        # CPR interpretation
        if cpr_width_percent < 0.3:
            cpr_type = "NARROW"
            cpr_signal = "Narrow CPR - Expect trending/breakout day"
        elif cpr_width_percent > 0.8:
            cpr_type = "WIDE"
            cpr_signal = "Wide CPR - Expect range-bound/sideways day"
        else:
            cpr_type = "NORMAL"
            cpr_signal = "Normal CPR - Watch price action at pivot levels"
        
        # Calculate support/resistance from pivot
        r1 = 2 * pivot - prev_low
        r2 = pivot + (prev_high - prev_low)
        r3 = prev_high + 2 * (pivot - prev_low)
        s1 = 2 * pivot - prev_high
        s2 = pivot - (prev_high - prev_low)
        s3 = prev_low - 2 * (prev_high - pivot)
        
        # Gap analysis
        gap = nifty_open - prev_close
        gap_percent = (gap / prev_close) * 100
        
        if abs(gap) > 80:
            gap_type = "LARGE"
            gap_signal = f"Large gap ({gap:+.0f} pts). High probability of trend day."
        elif abs(gap) < 30:
            gap_type = "SMALL"
            gap_signal = f"Small gap ({gap:+.0f} pts). Range-bound opening expected."
        else:
            gap_type = "MODERATE"
            gap_signal = f"Moderate gap ({gap:+.0f} pts). Watch initial price action."
        
        # Market trend
        change = nifty_close - prev_close
        change_pct = (change / prev_close) * 100
        
        result["success"] = True
        result["data"] = {
            "nifty_open": round(nifty_open, 2),
            "nifty_high": round(nifty_high, 2),
            "nifty_low": round(nifty_low, 2),
            "nifty_close": round(nifty_close, 2),
            "prev_close": round(prev_close, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "gap_points": round(gap, 2),
            "gap_percent": round(gap_percent, 2),
            "gap_type": gap_type,
            "gap_signal": gap_signal,
            "pivot": round(pivot, 2),
            "tc": round(tc, 2),
            "bc": round(bc, 2),
            "cpr_width": round(cpr_width, 2),
            "cpr_width_percent": round(cpr_width_percent, 3),
            "cpr_type": cpr_type,
            "cpr_signal": cpr_signal,
            "r1": round(r1, 2),
            "r2": round(r2, 2),
            "r3": round(r3, 2),
            "s1": round(s1, 2),
            "s2": round(s2, 2),
            "s3": round(s3, 2)
        }
        
    except Exception as e:
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
    
    return result


# ============ PHASE 3: STOCK-SPECIFIC ANALYSIS ============

def calculate_cpr_levels(prev_high, prev_low, prev_close):
    """Calculate Central Pivot Range levels."""
    pivot = (prev_high + prev_low + prev_close) / 3
    bc = (prev_high + prev_low) / 2
    tc = (pivot - bc) + pivot
    
    r1 = 2 * pivot - prev_low
    r2 = pivot + (prev_high - prev_low)
    r3 = prev_high + 2 * (pivot - prev_low)
    s1 = 2 * pivot - prev_high
    s2 = pivot - (prev_high - prev_low)
    s3 = prev_low - 2 * (prev_high - pivot)
    
    return {
        "pivot": round(pivot, 2),
        "tc": round(tc, 2),
        "bc": round(bc, 2),
        "r1": round(r1, 2),
        "r2": round(r2, 2),
        "r3": round(r3, 2),
        "s1": round(s1, 2),
        "s2": round(s2, 2),
        "s3": round(s3, 2)
    }


def calculate_gann_levels(price):
    """
    Calculate Gann Square of 9 levels.
    These are based on the geometric progression from the square root of the price.
    """
    sqrt_price = math.sqrt(price)
    
    # Gann increments (45-degree angles on Square of 9)
    increments = [0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0, 1.125, 1.25]
    
    resistance_levels = []
    support_levels = []
    
    for inc in increments:
        # Resistance: (sqrt + increment)^2
        res = (sqrt_price + inc) ** 2
        resistance_levels.append(round(res, 2))
        
        # Support: (sqrt - increment)^2
        sup = (sqrt_price - inc) ** 2
        if sup > 0:
            support_levels.append(round(sup, 2))
    
    return {
        "resistance": resistance_levels[:5],  # Top 5 resistance levels
        "support": sorted(support_levels, reverse=True)[:5]  # Top 5 support levels
    }


def get_stock_analysis_advanced(symbol):
    """
    Advanced stock analysis including:
    - Option chain with OI change tracking
    - IV Range calculation
    - CPR levels
    - Gann levels
    - VWAP estimation
    """
    result = {
        "symbol": symbol,
        "success": False,
        "error": None,
        "data": {}
    }
    
    try:
        # 1. GET OPTION CHAIN DATA
        df, oc_error = fetch_option_chain_with_retry(symbol)
        if df is None or df.empty:
            error_msg = oc_error or f"{symbol} is not available in F&O segment. Only F&O stocks are supported."
            if error_msg and any(key in error_msg.lower() for key in ['ssl', 'certificate']):
                error_msg = f"NSE option chain SSL handshake failed. Please retry in a minute. ({error_msg})"
            result["error"] = error_msg
            result["data"]["option_chain_error"] = error_msg
            return result
        
        expiry_col = 'Expiry_Date'
        strike_col = 'Strike_Price'
        ce_iv_col = 'CALLS_IV'
        pe_iv_col = 'PUTS_IV'
        call_oi_col = 'CALLS_OI'
        put_oi_col = 'PUTS_OI'
        call_oi_chg_col = 'CALLS_Chng_in_OI'
        put_oi_chg_col = 'PUTS_Chng_in_OI'
        call_ltp_col = 'CALLS_LTP'
        put_ltp_col = 'PUTS_LTP'
        
        # Get price/delivery data
        quote = capital_market.price_volume_and_deliverable_position_data(symbol, period='1M')
        
        if quote.empty:
            result["error"] = "No market data available"
            return result
        
        latest = quote.iloc[-1]
        previous = quote.iloc[-2] if len(quote) > 1 else latest
        
        current_price = _clean_numeric(latest['ClosePrice'])
        prev_high = _clean_numeric(previous['HighPrice'])
        prev_low = _clean_numeric(previous['LowPrice'])
        prev_close = _clean_numeric(previous['ClosePrice'])
        today_open = _clean_numeric(latest['OpenPrice'])
        today_high = _clean_numeric(latest['HighPrice'])
        today_low = _clean_numeric(latest['LowPrice'])
        volume = _clean_numeric(latest['TotalTradedQuantity'])
        delivery_percent = _clean_numeric(latest['%DlyQttoTradedQty'])
        
        # 2. FILTER FOR NEAREST EXPIRY
        df['Expiry_DT'] = pd.to_datetime(df[expiry_col], format='%d-%b-%Y', errors='coerce')
        today = datetime.now()
        
        future_expiries = df[df['Expiry_DT'] >= today]
        if future_expiries.empty:
            future_expiries = df
        
        nearest_expiry = future_expiries['Expiry_DT'].min()
        expiry_str = nearest_expiry.strftime('%d-%b-%Y')
        
        odo = df[df['Expiry_DT'] == nearest_expiry].copy()
        if odo.empty:
            result["error"] = "No option data for nearest expiry"
            return result
        
        # 3. IV RANGE CALCULATION (Step 5 from strategy)
        strikes = odo[strike_col].astype(float).values
        atm_strike = strikes[(np.abs(strikes - current_price)).argmin()]
        
        atm_row = odo[odo[strike_col] == atm_strike].iloc[0]
        ce_iv = float(atm_row[ce_iv_col]) if pd.notna(atm_row[ce_iv_col]) and atm_row[ce_iv_col] > 0 else 0
        pe_iv = float(atm_row[pe_iv_col]) if pd.notna(atm_row[pe_iv_col]) and atm_row[pe_iv_col] > 0 else 0
        
        if ce_iv == 0 and pe_iv == 0:
            nearby_rows = odo[(odo[strike_col] >= current_price * 0.95) & (odo[strike_col] <= current_price * 1.05)]
            if not nearby_rows.empty:
                ce_iv = nearby_rows[ce_iv_col].replace(0, np.nan).mean() or 20
                pe_iv = nearby_rows[pe_iv_col].replace(0, np.nan).mean() or 20
            else:
                ce_iv = pe_iv = 20
        
        atm_iv = (ce_iv + pe_iv) / 2 if (ce_iv > 0 and pe_iv > 0) else max(ce_iv, pe_iv, 20)
        
        # Daily IV Range = Price × IV × √(1/365)
        daily_iv_range = current_price * (atm_iv / 100) * math.sqrt(1/365)
        iv_range_high = current_price + daily_iv_range
        iv_range_low = current_price - daily_iv_range
        
        # 4. OI ANALYSIS with Change in OI (Step 8 - 4-Quadrant Matrix)
        odo['CE_OI'] = pd.to_numeric(odo[call_oi_col], errors='coerce').fillna(0)
        odo['PE_OI'] = pd.to_numeric(odo[put_oi_col], errors='coerce').fillna(0)
        odo['CE_OI_Chg'] = pd.to_numeric(odo.get(call_oi_chg_col, 0), errors='coerce').fillna(0)
        odo['PE_OI_Chg'] = pd.to_numeric(odo.get(put_oi_chg_col, 0), errors='coerce').fillna(0)
        
        # Max OI levels
        max_call_oi_row = odo.loc[odo['CE_OI'].idxmax()]
        max_put_oi_row = odo.loc[odo['PE_OI'].idxmax()]
        
        resistance_strike = float(max_call_oi_row[strike_col])
        support_strike = float(max_put_oi_row[strike_col])
        max_call_oi = float(max_call_oi_row['CE_OI'])
        max_put_oi = float(max_put_oi_row['PE_OI'])
        
        # Total OI and changes
        total_call_oi = odo['CE_OI'].sum()
        total_put_oi = odo['PE_OI'].sum()
        total_call_oi_chg = odo['CE_OI_Chg'].sum()
        total_put_oi_chg = odo['PE_OI_Chg'].sum()
        
        pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 1
        pcr_change = total_put_oi_chg / total_call_oi_chg if total_call_oi_chg != 0 else 0
        
        # 4-Quadrant Matrix Analysis
        price_change = current_price - prev_close
        price_up = price_change > 0
        oi_up = (total_call_oi_chg + total_put_oi_chg) > 0
        
        if price_up and oi_up:
            oi_interpretation = "LONG_BUILDUP"
            oi_signal = "Strong Uptrend - Long Buildup. Buy on dips."
        elif not price_up and oi_up:
            oi_interpretation = "SHORT_BUILDUP"
            oi_signal = "Strong Downtrend - Short Buildup. Sell on rise."
        elif not price_up and not oi_up:
            oi_interpretation = "LONG_UNWINDING"
            oi_signal = "Weakness - Long Unwinding. Caution, profit booking."
        else:  # price_up and not oi_up
            oi_interpretation = "SHORT_COVERING"
            oi_signal = "Explosive Rally - Short Covering. Fastest upside potential."
        
        # 5. MAX PAIN CALCULATION
        min_loss = float('inf')
        max_pain = 0
        
        for strike in strikes:
            call_loss = odo.apply(
                lambda x: max(0, strike - float(x[strike_col])) * x['CE_OI'], axis=1
            ).sum()
            put_loss = odo.apply(
                lambda x: max(0, float(x[strike_col]) - strike) * x['PE_OI'], axis=1
            ).sum()
            
            total_loss = call_loss + put_loss
            if total_loss < min_loss:
                min_loss = total_loss
                max_pain = strike
        
        # 6. CPR LEVELS (Step 6)
        cpr_levels = calculate_cpr_levels(prev_high, prev_low, prev_close)
        
        # CPR width analysis
        cpr_width = abs(cpr_levels['tc'] - cpr_levels['bc'])
        cpr_width_percent = (cpr_width / prev_close) * 100 if prev_close > 0 else 0
        
        if cpr_width_percent < 0.5:
            cpr_type = "NARROW"
            cpr_signal = "Narrow CPR - Breakout expected"
        elif cpr_width_percent > 1.5:
            cpr_type = "WIDE"
            cpr_signal = "Wide CPR - Sideways day expected"
        else:
            cpr_type = "NORMAL"
            cpr_signal = "Normal CPR - Trade pivot levels"
        
        # 7. GANN LEVELS (Step 7)
        gann_levels = calculate_gann_levels(current_price)
        
        # 8. VWAP ESTIMATION (Step 9)
        # True VWAP needs intraday data, but we can estimate from daily data
        # VWAP ≈ (High + Low + Close) / 3 * weighted by volume
        vwap_estimate = (today_high + today_low + current_price) / 3
        
        price_vs_vwap = "ABOVE" if current_price > vwap_estimate else "BELOW"
        vwap_signal = ""
        if price_vs_vwap == "ABOVE":
            vwap_signal = "Price above VWAP - Bullish intraday bias"
        else:
            vwap_signal = "Price below VWAP - Bearish intraday bias"
        
        # 9. RELATIVE STRENGTH (vs Nifty)
        try:
            nifty_data = capital_market.index_data('NIFTY 50', period='1M')
            if not nifty_data.empty:
                nifty_latest = nifty_data.iloc[-1]
                nifty_prev = nifty_data.iloc[-2] if len(nifty_data) > 1 else nifty_latest
                nifty_change_pct = ((_clean_numeric(nifty_latest['CLOSE_INDEX_VAL']) - 
                                    _clean_numeric(nifty_prev['CLOSE_INDEX_VAL'])) / 
                                   _clean_numeric(nifty_prev['CLOSE_INDEX_VAL'])) * 100
                stock_change_pct = (price_change / prev_close) * 100 if prev_close > 0 else 0
                relative_strength = stock_change_pct - nifty_change_pct
            else:
                nifty_change_pct = 0
                stock_change_pct = (price_change / prev_close) * 100 if prev_close > 0 else 0
                relative_strength = 0
        except:
            nifty_change_pct = 0
            stock_change_pct = (price_change / prev_close) * 100 if prev_close > 0 else 0
            relative_strength = 0
        
        # Build comprehensive result
        result["success"] = True
        result["data"] = {
            # Price Data
            "current_price": round(current_price, 2),
            "prev_close": round(prev_close, 2),
            "today_open": round(today_open, 2),
            "today_high": round(today_high, 2),
            "today_low": round(today_low, 2),
            "price_change": round(price_change, 2),
            "price_change_pct": round((price_change / prev_close) * 100, 2) if prev_close > 0 else 0,
            
            # Volume & Delivery
            "volume": int(volume),
            "delivery_percent": round(delivery_percent, 2),
            
            # Expiry Info
            "expiry": expiry_str,
            "atm_strike": float(atm_strike),
            
            # IV Analysis
            "atm_iv": round(atm_iv, 2),
            "ce_iv": round(ce_iv, 2),
            "pe_iv": round(pe_iv, 2),
            "daily_iv_range": round(daily_iv_range, 2),
            "iv_range_low": round(iv_range_low, 2),
            "iv_range_high": round(iv_range_high, 2),
            
            # OI Analysis
            "support_strike": support_strike,
            "resistance_strike": resistance_strike,
            "max_call_oi": max_call_oi,
            "max_put_oi": max_put_oi,
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "call_oi_change": total_call_oi_chg,
            "put_oi_change": total_put_oi_chg,
            "pcr": round(pcr, 2),
            "max_pain": float(max_pain),
            
            # 4-Quadrant Analysis
            "oi_interpretation": oi_interpretation,
            "oi_signal": oi_signal,
            
            # CPR Levels
            "cpr": cpr_levels,
            "cpr_width": round(cpr_width, 2),
            "cpr_type": cpr_type,
            "cpr_signal": cpr_signal,
            
            # Gann Levels
            "gann": gann_levels,
            
            # VWAP
            "vwap_estimate": round(vwap_estimate, 2),
            "price_vs_vwap": price_vs_vwap,
            "vwap_signal": vwap_signal,
            
            # Relative Strength
            "stock_change_pct": round(stock_change_pct, 2),
            "nifty_change_pct": round(nifty_change_pct, 2),
            "relative_strength": round(relative_strength, 2),
            
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
    
    return result


# ============ ADVANCED PREDICTION ENGINE ============

def calculate_advanced_prediction(stock_data, fii_data=None, market_data=None):
    """
    Advanced prediction using multi-factor analysis.
    Implements the complete strategy checklist.
    """
    checklist = []
    bullish_score = 0
    bearish_score = 0
    total_weight = 0
    
    # 1. FII/DII Analysis (Weight: 15)
    weight = 15
    total_weight += weight
    if fii_data and fii_data.get("success"):
        fii_info = fii_data["data"]
        fii_bias = fii_info.get("fii_bias", "NEUTRAL")
        fii_long_ratio = fii_info.get("fii_long_ratio", 50)
        
        if fii_bias == "BULLISH":
            bullish_score += weight
            checklist.append({"factor": "FII Activity", "status": "PASS", "value": f"Net Buyers (Long Ratio: {fii_long_ratio}%)", "impact": "bullish", "weight": weight})
        elif fii_bias == "BEARISH":
            bearish_score += weight
            checklist.append({"factor": "FII Activity", "status": "FAIL", "value": f"Net Sellers (Long Ratio: {fii_long_ratio}%)", "impact": "bearish", "weight": weight})
        elif fii_bias == "OVERSOLD":
            bullish_score += weight * 0.7  # Contrarian
            checklist.append({"factor": "FII Activity", "status": "PASS", "value": f"Oversold - Bounce Expected (Long Ratio: {fii_long_ratio}%)", "impact": "bullish", "weight": weight})
        elif fii_bias == "OVERBOUGHT":
            bearish_score += weight * 0.7  # Contrarian
            checklist.append({"factor": "FII Activity", "status": "FAIL", "value": f"Overbought - Correction Expected (Long Ratio: {fii_long_ratio}%)", "impact": "bearish", "weight": weight})
        else:
            checklist.append({"factor": "FII Activity", "status": "NEUTRAL", "value": "Neutral", "impact": "neutral", "weight": weight})
    else:
        checklist.append({"factor": "FII Activity", "status": "N/A", "value": "Data unavailable", "impact": "neutral", "weight": weight})
    
    # 2. Market Gap Analysis (Weight: 10)
    weight = 10
    total_weight += weight
    if market_data and market_data.get("success"):
        gap_type = market_data["data"].get("gap_type", "SMALL")
        gap_points = market_data["data"].get("gap_points", 0)
        
        if gap_type == "LARGE" and gap_points > 0:
            bullish_score += weight
            checklist.append({"factor": "Market Gap", "status": "PASS", "value": f"+{gap_points} pts (Trend Day)", "impact": "bullish", "weight": weight})
        elif gap_type == "LARGE" and gap_points < 0:
            bearish_score += weight
            checklist.append({"factor": "Market Gap", "status": "FAIL", "value": f"{gap_points} pts (Trend Day)", "impact": "bearish", "weight": weight})
        else:
            checklist.append({"factor": "Market Gap", "status": "NEUTRAL", "value": f"{gap_points} pts (Range-bound)", "impact": "neutral", "weight": weight})
    else:
        checklist.append({"factor": "Market Gap", "status": "N/A", "value": "Data unavailable", "impact": "neutral", "weight": weight})
    
    # 3. Price vs CPR (Weight: 12)
    weight = 12
    total_weight += weight
    cpr = stock_data.get("cpr", {})
    current_price = stock_data.get("current_price", 0)
    pivot = cpr.get("pivot", current_price)
    tc = cpr.get("tc", current_price)
    bc = cpr.get("bc", current_price)
    
    if current_price > tc:
        bullish_score += weight
        checklist.append({"factor": "Price vs CPR", "status": "PASS", "value": f"Above TC ({tc}) - Bullish", "impact": "bullish", "weight": weight})
    elif current_price < bc:
        bearish_score += weight
        checklist.append({"factor": "Price vs CPR", "status": "FAIL", "value": f"Below BC ({bc}) - Bearish", "impact": "bearish", "weight": weight})
    elif current_price > pivot:
        bullish_score += weight * 0.5
        checklist.append({"factor": "Price vs CPR", "status": "PASS", "value": f"Above Pivot ({pivot})", "impact": "bullish", "weight": weight})
    else:
        bearish_score += weight * 0.5
        checklist.append({"factor": "Price vs CPR", "status": "FAIL", "value": f"Below Pivot ({pivot})", "impact": "bearish", "weight": weight})
    
    # 4. Price vs VWAP (Weight: 10)
    weight = 10
    total_weight += weight
    vwap = stock_data.get("vwap_estimate", current_price)
    price_vs_vwap = stock_data.get("price_vs_vwap", "ABOVE")
    
    if price_vs_vwap == "ABOVE":
        bullish_score += weight
        checklist.append({"factor": "Price vs VWAP", "status": "PASS", "value": f"Above VWAP ({vwap})", "impact": "bullish", "weight": weight})
    else:
        bearish_score += weight
        checklist.append({"factor": "Price vs VWAP", "status": "FAIL", "value": f"Below VWAP ({vwap})", "impact": "bearish", "weight": weight})
    
    # 5. OI Interpretation - 4-Quadrant (Weight: 18)
    weight = 18
    total_weight += weight
    oi_interp = stock_data.get("oi_interpretation", "NEUTRAL")
    
    if oi_interp == "LONG_BUILDUP":
        bullish_score += weight
        checklist.append({"factor": "OI Analysis", "status": "PASS", "value": "Long Buildup - Strong Uptrend", "impact": "bullish", "weight": weight})
    elif oi_interp == "SHORT_COVERING":
        bullish_score += weight * 0.8
        checklist.append({"factor": "OI Analysis", "status": "PASS", "value": "Short Covering - Explosive Rally", "impact": "bullish", "weight": weight})
    elif oi_interp == "SHORT_BUILDUP":
        bearish_score += weight
        checklist.append({"factor": "OI Analysis", "status": "FAIL", "value": "Short Buildup - Strong Downtrend", "impact": "bearish", "weight": weight})
    elif oi_interp == "LONG_UNWINDING":
        bearish_score += weight * 0.8
        checklist.append({"factor": "OI Analysis", "status": "FAIL", "value": "Long Unwinding - Weakness", "impact": "bearish", "weight": weight})
    else:
        checklist.append({"factor": "OI Analysis", "status": "NEUTRAL", "value": "No clear signal", "impact": "neutral", "weight": weight})
    
    # 6. PCR Analysis (Weight: 10)
    weight = 10
    total_weight += weight
    pcr = stock_data.get("pcr", 1)
    
    if pcr > 1.2:
        bullish_score += weight
        checklist.append({"factor": "PCR", "status": "PASS", "value": f"{pcr} (Bullish - High Put Writing)", "impact": "bullish", "weight": weight})
    elif pcr < 0.7:
        bearish_score += weight
        checklist.append({"factor": "PCR", "status": "FAIL", "value": f"{pcr} (Bearish - High Call Writing)", "impact": "bearish", "weight": weight})
    else:
        checklist.append({"factor": "PCR", "status": "NEUTRAL", "value": f"{pcr} (Neutral)", "impact": "neutral", "weight": weight})
    
    # 7. Price within IV Range (Weight: 8)
    weight = 8
    total_weight += weight
    iv_low = stock_data.get("iv_range_low", 0)
    iv_high = stock_data.get("iv_range_high", float('inf'))
    
    if iv_low <= current_price <= iv_high:
        checklist.append({"factor": "IV Range", "status": "PASS", "value": f"Within range ({iv_low}-{iv_high})", "impact": "neutral", "weight": weight})
    elif current_price > iv_high:
        bearish_score += weight * 0.5  # Mean reversion expected
        checklist.append({"factor": "IV Range", "status": "WARN", "value": f"Above IV range - Mean reversion likely", "impact": "bearish", "weight": weight})
    else:
        bullish_score += weight * 0.5  # Mean reversion expected
        checklist.append({"factor": "IV Range", "status": "WARN", "value": f"Below IV range - Mean reversion likely", "impact": "bullish", "weight": weight})
    
    # 8. Delivery Analysis (Weight: 12)
    weight = 12
    total_weight += weight
    delivery_pct = stock_data.get("delivery_percent", 0)
    price_change = stock_data.get("price_change", 0)
    
    if price_change > 0 and delivery_pct >= 50:
        bullish_score += weight
        checklist.append({"factor": "Delivery", "status": "PASS", "value": f"{delivery_pct}% - Genuine Buying", "impact": "bullish", "weight": weight})
    elif price_change > 0 and delivery_pct < 30:
        bearish_score += weight * 0.7
        checklist.append({"factor": "Delivery", "status": "WARN", "value": f"{delivery_pct}% - Speculative Rise", "impact": "bearish", "weight": weight})
    elif price_change < 0 and delivery_pct >= 50:
        bearish_score += weight
        checklist.append({"factor": "Delivery", "status": "FAIL", "value": f"{delivery_pct}% - Genuine Selling", "impact": "bearish", "weight": weight})
    elif price_change < 0 and delivery_pct < 30:
        bullish_score += weight * 0.5
        checklist.append({"factor": "Delivery", "status": "WARN", "value": f"{delivery_pct}% - Panic Selling (Bounce likely)", "impact": "bullish", "weight": weight})
    else:
        checklist.append({"factor": "Delivery", "status": "NEUTRAL", "value": f"{delivery_pct}%", "impact": "neutral", "weight": weight})
    
    # 9. Relative Strength (Weight: 5)
    weight = 5
    total_weight += weight
    rs = stock_data.get("relative_strength", 0)
    
    if rs > 1:
        bullish_score += weight
        checklist.append({"factor": "Relative Strength", "status": "PASS", "value": f"+{rs}% vs Nifty (Outperforming)", "impact": "bullish", "weight": weight})
    elif rs < -1:
        bearish_score += weight
        checklist.append({"factor": "Relative Strength", "status": "FAIL", "value": f"{rs}% vs Nifty (Underperforming)", "impact": "bearish", "weight": weight})
    else:
        checklist.append({"factor": "Relative Strength", "status": "NEUTRAL", "value": f"{rs}% vs Nifty", "impact": "neutral", "weight": weight})
    
    # Calculate final prediction
    total_score = bullish_score + bearish_score
    
    if total_score == 0:
        prediction = "NEUTRAL"
        confidence = 50
    else:
        bullish_pct = (bullish_score / total_weight) * 100
        bearish_pct = (bearish_score / total_weight) * 100
        
        if bullish_score > bearish_score * 1.3:
            prediction = "BULLISH"
            confidence = min(int(bullish_pct), 85)
        elif bearish_score > bullish_score * 1.3:
            prediction = "BEARISH"
            confidence = min(int(bearish_pct), 85)
        else:
            prediction = "NEUTRAL"
            confidence = 50
    
    # Count checklist passes
    passes = sum(1 for item in checklist if item["status"] == "PASS")
    fails = sum(1 for item in checklist if item["status"] == "FAIL")
    
    # Determine action
    if prediction == "BULLISH" and passes >= 5:
        action = "BUY"
        action_detail = "Multiple bullish confirmations. Look for dip buying opportunities."
    elif prediction == "BEARISH" and fails >= 5:
        action = "SELL"
        action_detail = "Multiple bearish confirmations. Look for rally selling opportunities."
    elif prediction == "NEUTRAL":
        action = "WAIT"
        action_detail = "Mixed signals. Wait for clearer direction or trade range."
    else:
        action = "CAUTION"
        action_detail = "Some confirmations but not enough conviction. Trade with tight stops."
    
    return {
        "prediction": prediction,
        "confidence": confidence,
        "action": action,
        "action_detail": action_detail,
        "bullish_score": round(bullish_score, 1),
        "bearish_score": round(bearish_score, 1),
        "total_weight": total_weight,
        "checklist_passes": passes,
        "checklist_fails": fails,
        "checklist": checklist
    }


# ============ TODAY'S PICKS - SMART STOCK SCREENING ============

# Simple cache for today's picks (refreshes every 5 minutes)
_picks_cache = {
    "data": None,
    "timestamp": None,
    "sectors_data": None,
    "sectors_timestamp": None
}
CACHE_DURATION_MINUTES = 5

# Sector to Stock Mapping (Major F&O Stocks by Sector) - Limited to top stocks for faster screening
SECTOR_STOCKS = {
    "NIFTY BANK": ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN", "INDUSINDBK"],
    "NIFTY IT": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM"],
    "NIFTY AUTO": ["TATAMOTORS", "M&M", "MARUTI", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT"],
    "NIFTY PHARMA": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP", "LUPIN"],
    "NIFTY METAL": ["TATASTEEL", "HINDALCO", "JSWSTEEL", "COALINDIA", "VEDL", "NMDC"],
    "NIFTY ENERGY": ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "TATAPOWER", "BPCL"],
    "NIFTY FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "MARICO"],
    "NIFTY REALTY": ["DLF", "GODREJPROP", "OBEROIRLTY", "PHOENIXLTD"],
    "NIFTY FIN SERVICE": ["BAJFINANCE", "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "CHOLAFIN", "SHRIRAMFIN"],
    "NIFTY PRIVATE BANK": ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK", "FEDERALBNK"]
}

# All sector indices to track
SECTOR_INDICES = [
    "NIFTY BANK", "NIFTY IT", "NIFTY AUTO", "NIFTY PHARMA", "NIFTY METAL",
    "NIFTY ENERGY", "NIFTY FMCG", "NIFTY REALTY", "NIFTY INFRA", "NIFTY FIN SERVICE",
    "NIFTY MEDIA", "NIFTY PSU BANK", "NIFTY PRIVATE BANK", "NIFTY HEALTHCARE INDEX"
]


def get_sector_performance():
    """
    Step 1: Identify the "Sector in Play"
    Get live performance of all sector indices and identify strongest sectors.
    Uses caching to avoid repeated API calls.
    """
    global _picks_cache
    
    # Check cache first
    if _picks_cache["sectors_data"] and _picks_cache["sectors_timestamp"]:
        cache_age = (datetime.now() - _picks_cache["sectors_timestamp"]).total_seconds() / 60
        if cache_age < CACHE_DURATION_MINUTES:
            return _picks_cache["sectors_data"]
    
    result = {
        "success": False,
        "sectors": [],
        "nifty_change": 0,
        "sector_in_play": None,
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        import requests
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.nseindia.com/'
        }
        
        session = requests.Session()
        # First hit main page to get cookies
        session.get('https://www.nseindia.com', headers=headers, timeout=10)
        
        # Get all indices data
        response = session.get('https://www.nseindia.com/api/allIndices', headers=headers, timeout=10)
        data = response.json()
        
        indices_data = data.get('data', [])
        
        # Find Nifty 50 change
        nifty_change = 0
        for idx in indices_data:
            if idx.get('index') == 'NIFTY 50':
                nifty_change = float(idx.get('percentChange', 0))
                break
        
        result["nifty_change"] = nifty_change
        
        # Filter and sort sector indices
        sectors = []
        for idx in indices_data:
            index_name = idx.get('index', '')
            if any(sector in index_name for sector in ['BANK', 'IT', 'AUTO', 'PHARMA', 'METAL', 'ENERGY', 
                                                        'FMCG', 'REALTY', 'INFRA', 'FIN', 'MEDIA', 'PSU', 
                                                        'PRIVATE', 'HEALTHCARE', 'OIL', 'CONSUMER']):
                pct_change = float(idx.get('percentChange', 0))
                relative_strength = pct_change - nifty_change
                
                sectors.append({
                    "name": index_name,
                    "change_pct": round(pct_change, 2),
                    "relative_strength": round(relative_strength, 2),
                    "last": float(idx.get('last', 0)),
                    "open": float(idx.get('open', 0)),
                    "high": float(idx.get('high', 0)),
                    "low": float(idx.get('low', 0)),
                    "is_outperforming": relative_strength > 0.3  # Outperforming Nifty by 0.3%+
                })
        
        # Sort by relative strength (descending)
        sectors.sort(key=lambda x: x['relative_strength'], reverse=True)
        result["sectors"] = sectors[:15]  # Top 15 sectors
        
        # Identify sector in play (strongest outperformer)
        outperformers = [s for s in sectors if s['is_outperforming']]
        if outperformers:
            result["sector_in_play"] = outperformers[0]['name']
        
        result["success"] = True
        
        # Cache the result
        _picks_cache["sectors_data"] = result
        _picks_cache["sectors_timestamp"] = datetime.now()
        
    except Exception as e:
        result["error"] = str(e)
        traceback.print_exc()
    
    return result


def screen_stocks_in_sector(sector_name, quick_mode=False):
    """
    Step 2: Smart Money Screener
    Screen stocks in the given sector for:
    - Price > VWAP
    - Relative Strength > Nifty
    - Volume > Previous day
    - OI Buildup (Long Buildup preferred)
    """
    result = {
        "success": False,
        "sector": sector_name,
        "stocks": [],
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        # Find matching sector key
        sector_key = None
        for key in SECTOR_STOCKS.keys():
            if key in sector_name or sector_name in key:
                sector_key = key
                break
        
        if not sector_key:
            # Try partial match
            for key in SECTOR_STOCKS.keys():
                key_words = key.replace("NIFTY ", "").split()
                if any(word in sector_name for word in key_words):
                    sector_key = key
                    break
        
        if not sector_key:
            result["error"] = f"No stocks mapped for sector: {sector_name}"
            return result
        
        # Limit to first 5 stocks to avoid rate limiting and timeouts
        stocks_to_screen = SECTOR_STOCKS[sector_key][:5]
        screened_stocks = []
        
        # Get Nifty change for relative strength calculation
        try:
            nifty_data = capital_market.index_data('NIFTY 50', period='1M')
            if not nifty_data.empty:
                latest_nifty = nifty_data.iloc[-1]
                prev_nifty = nifty_data.iloc[-2] if len(nifty_data) > 1 else latest_nifty
                nifty_change_pct = ((float(latest_nifty['CLOSE_INDEX_VAL']) - float(prev_nifty['CLOSE_INDEX_VAL'])) / float(prev_nifty['CLOSE_INDEX_VAL'])) * 100
            else:
                nifty_change_pct = 0
        except:
            nifty_change_pct = 0
        
        for symbol in stocks_to_screen:
            try:
                # Add small delay to avoid rate limiting
                time.sleep(0.5)
                
                stock_score = 0
                stock_data = {
                    "symbol": symbol,
                    "score": 0,
                    "signals": [],
                    "price": 0,
                    "change_pct": 0,
                    "vwap": 0,
                    "price_vs_vwap": "N/A",
                    "relative_strength": 0,
                    "oi_interpretation": "N/A",
                    "volume_surge": False
                }
                
                # Get price and delivery data
                quote = capital_market.price_volume_and_deliverable_position_data(symbol, period='1M')
                
                if quote.empty:
                    continue
                
                latest = quote.iloc[-1]
                prev = quote.iloc[-2] if len(quote) > 1 else latest
                
                # Current price and change
                current_price = _clean_numeric(latest.get('ClosePrice', 0))
                prev_close = _clean_numeric(prev.get('ClosePrice', 0))
                
                if current_price == 0:
                    continue
                
                price_change_pct = ((current_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                stock_data["price"] = current_price
                stock_data["change_pct"] = round(price_change_pct, 2)
                
                # Calculate VWAP estimate
                today_high = _clean_numeric(latest.get('HighPrice', current_price))
                today_low = _clean_numeric(latest.get('LowPrice', current_price))
                vwap_estimate = (today_high + today_low + current_price) / 3
                stock_data["vwap"] = round(vwap_estimate, 2)
                
                # Check 1: Price > VWAP
                if current_price > vwap_estimate:
                    stock_score += 25
                    stock_data["price_vs_vwap"] = "ABOVE"
                    stock_data["signals"].append("Price > VWAP ✓")
                else:
                    stock_data["price_vs_vwap"] = "BELOW"
                
                # Check 2: Relative Strength > Nifty
                relative_strength = price_change_pct - nifty_change_pct
                stock_data["relative_strength"] = round(relative_strength, 2)
                if relative_strength > 0:
                    stock_score += 20
                    stock_data["signals"].append(f"RS +{relative_strength:.1f}% vs Nifty ✓")
                
                # Check 3: Volume Surge
                try:
                    current_vol = _clean_numeric(latest.get('TotalTradedQty', 0))
                    prev_vol = _clean_numeric(prev.get('TotalTradedQty', 0))
                    if current_vol > prev_vol * 1.2:  # 20% volume surge
                        stock_score += 15
                        stock_data["volume_surge"] = True
                        stock_data["signals"].append("Volume Surge ✓")
                except:
                    pass
                
                # Check 4: Delivery % (genuine buying)
                try:
                    delivery_pct = _clean_numeric(latest.get('%DlyQttoTradedQty', 0))
                    if delivery_pct > 50:
                        stock_score += 15
                        stock_data["signals"].append(f"Delivery {delivery_pct:.0f}% ✓")
                except:
                    pass
                
                # Check 5: OI Analysis (Long Buildup) - Skip in quick mode
                if not quick_mode:
                    df, oc_error = fetch_option_chain_with_retry(symbol, retries=2, backoff_seconds=1)
                    if df is not None and not df.empty:
                        # Get ATM strike OI changes
                        total_call_oi_chg = df['CALLS_Chng_in_OI'].sum() if 'CALLS_Chng_in_OI' in df.columns else 0
                        total_put_oi_chg = df['PUTS_Chng_in_OI'].sum() if 'PUTS_Chng_in_OI' in df.columns else 0
                        
                        # Determine OI interpretation
                        if price_change_pct > 0 and total_put_oi_chg > total_call_oi_chg:
                            stock_data["oi_interpretation"] = "LONG_BUILDUP"
                            stock_score += 25
                            stock_data["signals"].append("Long Buildup ✓")
                        elif price_change_pct > 0 and total_call_oi_chg < 0:
                            stock_data["oi_interpretation"] = "SHORT_COVERING"
                            stock_score += 20
                            stock_data["signals"].append("Short Covering ✓")
                        elif price_change_pct < 0 and total_call_oi_chg > total_put_oi_chg:
                            stock_data["oi_interpretation"] = "SHORT_BUILDUP"
                            stock_data["signals"].append("Short Buildup ⚠")
                        else:
                            stock_data["oi_interpretation"] = "NEUTRAL"
                    else:
                        if oc_error and any(key in oc_error.lower() for key in ['ssl', 'certificate']):
                            stock_data["signals"].append("OI skipped (SSL error)")
                else:
                    # In quick mode, estimate OI interpretation from price action
                    if price_change_pct > 0.5 and stock_data["price_vs_vwap"] == "ABOVE":
                        stock_data["oi_interpretation"] = "BULLISH"
                        stock_score += 15
                    elif price_change_pct < -0.5:
                        stock_data["oi_interpretation"] = "BEARISH"
                
                stock_data["score"] = stock_score
                
                # Only include stocks with score >= 35 (lowered for quick mode)
                min_score = 35 if quick_mode else 40
                if stock_score >= min_score:
                    screened_stocks.append(stock_data)
                
            except Exception as e:
                continue
        
        # Sort by score (descending)
        screened_stocks.sort(key=lambda x: x['score'], reverse=True)
        result["stocks"] = screened_stocks[:10]  # Top 10 stocks
        result["success"] = True
        
    except Exception as e:
        result["error"] = str(e)
        traceback.print_exc()
    
    return result


def get_todays_picks_fast():
    """
    Fast "Today's Picks" - returns sector data and market status immediately.
    Stock screening is done separately to avoid timeout.
    """
    result = {
        "success": False,
        "timestamp": datetime.now().isoformat(),
        "market_status": "ANALYZING",
        "nifty_change": 0,
        "sectors": [],
        "sector_in_play": None,
        "top_picks": [],
        "bullish_picks": [],
        "bearish_picks": []
    }
    
    try:
        # Get Sector Performance (fast)
        sector_data = get_sector_performance()
        
        if not sector_data.get("success"):
            result["error"] = "Failed to fetch sector data"
            return result
        
        result["nifty_change"] = sector_data["nifty_change"]
        result["sectors"] = sector_data["sectors"][:8]
        result["sector_in_play"] = sector_data.get("sector_in_play")
        
        # Determine market status
        if sector_data["nifty_change"] > 0.5:
            result["market_status"] = "BULLISH"
        elif sector_data["nifty_change"] < -0.5:
            result["market_status"] = "BEARISH"
        else:
            result["market_status"] = "RANGE_BOUND"
        
        # Return suggested stocks from top sectors (without live screening)
        # This gives instant response while providing useful stock suggestions
        top_sectors = [s for s in sector_data["sectors"] if s['is_outperforming']][:2]
        if not top_sectors:
            top_sectors = sorted(sector_data["sectors"], key=lambda x: x['relative_strength'], reverse=True)[:2]
        
        # Add quick stock suggestions from each sector
        for sector in top_sectors:
            sector_key = None
            for key in SECTOR_STOCKS.keys():
                if key in sector["name"] or sector["name"] in key:
                    sector_key = key
                    break
                key_words = key.replace("NIFTY ", "").split()
                if any(word in sector["name"] for word in key_words):
                    sector_key = key
                    break
            
            if sector_key:
                for symbol in SECTOR_STOCKS[sector_key][:3]:  # Top 3 stocks per sector
                    result["top_picks"].append({
                        "symbol": symbol,
                        "sector": sector["name"],
                        "sector_rs": sector["relative_strength"],
                        "score": 50,  # Placeholder score
                        "signals": [f"Sector Outperforming ({sector['relative_strength']:.2f}% RS)"],
                        "oi_interpretation": "PENDING",
                        "change_pct": 0,
                        "price": 0
                    })
        
        result["success"] = True
        
    except Exception as e:
        result["error"] = str(e)
        traceback.print_exc()
    
    return result


def get_todays_picks():
    """
    Complete "Today's Picks" analysis:
    1. Get sector performance
    2. Screen stocks in top sectors
    3. Add institutional validation
    4. Return curated list
    """
    result = {
        "success": False,
        "timestamp": datetime.now().isoformat(),
        "market_status": "ANALYZING",
        "nifty_change": 0,
        "sectors": [],
        "sector_in_play": None,
        "top_picks": [],
        "bullish_picks": [],
        "bearish_picks": []
    }
    
    global picks_cache, cache_timestamp
    
    # Check cache first
    if picks_cache and cache_timestamp:
        cache_age = (datetime.now() - cache_timestamp).total_seconds()
        if cache_age < CACHE_DURATION:
            print(f"Returning cached picks (age: {cache_age:.0f}s)")
            return picks_cache
    
    try:
        # Step 1: Get Sector Performance
        sector_data = get_sector_performance()
        
        if not sector_data.get("success"):
            result["error"] = "Failed to fetch sector data"
            return result
        
        result["nifty_change"] = sector_data["nifty_change"]
        result["sectors"] = sector_data["sectors"][:8]  # Top 8 sectors
        result["sector_in_play"] = sector_data.get("sector_in_play")
        
        # Determine market status
        if sector_data["nifty_change"] > 0.5:
            result["market_status"] = "BULLISH"
        elif sector_data["nifty_change"] < -0.5:
            result["market_status"] = "BEARISH"
        else:
            result["market_status"] = "RANGE_BOUND"
        
        # Step 2: Screen stocks from top 2 outperforming sectors (limited for speed)
        all_screened = []
        top_sectors = [s for s in sector_data["sectors"] if s['is_outperforming']][:2]
        
        # If no outperforming sectors, take top 2 by relative strength
        if not top_sectors:
            top_sectors = sorted(sector_data["sectors"], key=lambda x: x['relative_strength'], reverse=True)[:2]
        
        for sector in top_sectors[:2]:  # Ensure max 2 sectors
            print(f"Screening sector: {sector['name']}")
            sector_stocks = screen_stocks_in_sector(sector["name"], quick_mode=True)
            if sector_stocks.get("success"):
                for stock in sector_stocks.get("stocks", []):
                    stock["sector"] = sector["name"]
                    stock["sector_rs"] = sector["relative_strength"]
                    all_screened.append(stock)
        
        # Sort all screened stocks by score
        all_screened.sort(key=lambda x: x['score'], reverse=True)
        
        # Categorize picks
        for stock in all_screened:
            if stock["oi_interpretation"] in ["LONG_BUILDUP", "SHORT_COVERING"]:
                result["bullish_picks"].append(stock)
            elif stock["oi_interpretation"] == "SHORT_BUILDUP":
                result["bearish_picks"].append(stock)
        
        # Top picks (best of all)
        result["top_picks"] = all_screened[:5]
        result["bullish_picks"] = result["bullish_picks"][:5]
        result["bearish_picks"] = result["bearish_picks"][:3]
        
        result["success"] = True
        
        # Cache the result
        picks_cache = result
        cache_timestamp = datetime.now()
        print("Picks cached successfully")
        
    except Exception as e:
        result["error"] = str(e)
        traceback.print_exc()
    
    return result


# ============ API ROUTES ============

@app.route('/')
def serve_frontend():
    """Serve the main frontend HTML file."""
    return send_from_directory('.', 'index_advanced.html')


@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "version": "2.0", "timestamp": datetime.now().isoformat()})


@app.route('/api/fii-dii', methods=['GET'])
def fii_dii_endpoint():
    """Get FII/DII activity data."""
    return jsonify(get_fii_dii_data())


@app.route('/api/market-overview', methods=['GET'])
def market_overview_endpoint():
    """Get market overview with Nifty CPR levels."""
    return jsonify(get_market_overview())


@app.route('/api/analyze/<symbol>', methods=['GET'])
def analyze_stock_endpoint(symbol):
    """Get advanced stock analysis."""
    symbol = symbol.upper().strip()
    return jsonify(get_stock_analysis_advanced(symbol))


@app.route('/api/full-analysis/<symbol>', methods=['GET'])
def full_analysis_endpoint(symbol):
    """Get comprehensive analysis with prediction."""
    symbol = symbol.upper().strip()
    
    # Get all data
    stock_data = get_stock_analysis_advanced(symbol)
    fii_data = get_fii_dii_data()
    market_data = get_market_overview()
    
    # Build response
    result = {
        "symbol": symbol,
        "timestamp": datetime.now().isoformat(),
        "stock_analysis": stock_data,
        "fii_dii": fii_data,
        "market_overview": market_data
    }
    
    # Calculate prediction if stock data succeeded
    if stock_data["success"]:
        prediction = calculate_advanced_prediction(
            stock_data["data"],
            fii_data if fii_data.get("success") else None,
            market_data if market_data.get("success") else None
        )
        result["prediction"] = prediction
        result["success"] = True
    else:
        result["success"] = False
        result["error"] = stock_data.get("error")
    
    return jsonify(result)


@app.route('/api/sectors', methods=['GET'])
def sectors_endpoint():
    """Get live sector performance data."""
    return jsonify(get_sector_performance())


@app.route('/api/screen-sector/<sector_name>', methods=['GET'])
def screen_sector_endpoint(sector_name):
    """Screen stocks in a specific sector."""
    return jsonify(screen_stocks_in_sector(sector_name))


@app.route('/api/todays-picks', methods=['GET'])
def todays_picks_endpoint():
    """Get curated stock picks for today (fast mode - returns sector data with suggested stocks)."""
    # Use fast mode by default to avoid timeouts
    return jsonify(get_todays_picks_fast())


@app.route('/api/todays-picks-full', methods=['GET'])
def todays_picks_full_endpoint():
    """Get complete stock picks with full screening (slower, may timeout)."""
    return jsonify(get_todays_picks())


@app.route('/api/ai/chat', methods=['POST'])
def ai_chat_proxy():
    """
    Proxy endpoint to forward AI chat completions to GROQ (server-side) using a secure env var.
    POST body should contain JSON with the payload expected by groq chat completions (e.g., messages, model, temperature)
    """
    data = request.get_json() or {}
    groq_key = os.getenv('GROQ_API_KEY', '')

    if not groq_key:
        return jsonify({"error": "GROQ_API_KEY not configured on server."}), 400

    groq_url = 'https://api.groq.com/openai/v1/chat/completions'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {groq_key}'
    }

    if not isinstance(data, dict):
        return jsonify({"error": "Invalid request body"}), 400

    if 'model' not in data or 'messages' not in data:
        return jsonify({"error": "Request must include 'model' and 'messages'"}), 400

    try:
        resp = requests.post(groq_url, headers=headers, json=data, timeout=30)
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text}
        return jsonify(body), resp.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/ai/health', methods=['GET'])
def ai_health():
    groq_key = os.getenv('GROQ_API_KEY', '')
    return jsonify({"groq_key_configured": bool(groq_key)})


if __name__ == "__main__":
    print("\n" + "="*60)
    print("  Stock Prediction Lab v2.0 - Advanced Analysis Engine")
    print("="*60)
    print("\n[*] Starting server at http://localhost:5000")
    print("\n[*] API Endpoints:")
    print("   GET /api/health               - Health check")
    print("   GET /api/fii-dii              - FII/DII activity data")
    print("   GET /api/market-overview      - Nifty overview & CPR")
    print("   GET /api/analyze/<symbol>     - Stock analysis")
    print("   GET /api/full-analysis/<symbol> - Complete prediction")
    print("   GET /api/sectors              - Live sector performance")
    print("   GET /api/todays-picks         - AI Stock Picks of the Day")
    print("\n[*] Analysis Features:")
    print("   + FII/DII Flow Analysis")
    print("   + Central Pivot Range (CPR)")
    print("   + IV Range Calculation")
    print("   + OI 4-Quadrant Matrix")
    print("   + VWAP Analysis")
    print("   + Gann Square of 9 Levels")
    print("   + Relative Strength")
    print("   + Multi-Factor Prediction")
    print("   + Sector-in-Play Detection")
    print("   + Smart Stock Screening")
    print("\n" + "="*60 + "\n")
    
    app.run(host='0.0.0.0', debug=False, port=5000, threaded=True)


# -- API-friendly error handlers --
@app.errorhandler(404)
def handle_404(e):
    # Return JSON for API routes so frontend doesn't attempt to parse HTML
    if request.path.startswith('/api'):
        return jsonify({"error": "Not Found", "path": request.path}), 404
    # Default: let Flask return the usual 404 (or serve index)
    return e


@app.errorhandler(405)
def handle_405(e):
    if request.path.startswith('/api'):
        return jsonify({"error": "Method Not Allowed", "path": request.path}), 405
    return e


@app.errorhandler(500)
def handle_500(e):
    if request.path.startswith('/api'):
        return jsonify({"error": "Server Error"}), 500
    return e

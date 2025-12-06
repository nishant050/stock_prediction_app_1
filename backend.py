import nselib
from nselib import derivatives
from nselib import capital_market
import pandas as pd
import numpy as np
from datetime import datetime

# --- Configuration ---
SYMBOL = "WIPRO"  # Stock Symbol (No need for .NS)


def _pick_column(df, candidates, label):
    """Return the first matching column name present in df."""
    for name in candidates:
        if name in df.columns:
            return name
    raise KeyError(f"Required column '{label}' not available in NSE response.")

def get_live_trap_check(symbol):
    print(f"--- 4-STEP TRAP CHECK FOR {symbol} ---\n")
    print("Fetching data from NSE (this may take 5-10 seconds)...")

    try:
        # 1. GET OPTION CHAIN DATA
        # nselib fetches the full live table from NSE
        df = derivatives.nse_live_option_chain(symbol)
        
        # Clean column names (NSE sometimes uses spaces or dots)
        df.columns = [c.strip().lower().replace(" ", "_").replace(".", "_") for c in df.columns]

        expiry_col = _pick_column(df, ["expiry_date", "expiry", "expiry_dt"], "Expiry Date")
        strike_col = _pick_column(df, ["strike_price", "strike", "strikeprice"], "Strike Price")
        ce_iv_col = _pick_column(df, ["ce_iv", "call_iv", "iv_call", "calls_iv"], "CE IV")
        pe_iv_col = _pick_column(df, ["pe_iv", "put_iv", "iv_put", "puts_iv"], "PE IV")
        call_oi_col = _pick_column(df, ["calls_oi", "call_oi", "ce_open_interest", "ce_oi"], "Call OI")
        put_oi_col = _pick_column(df, ["puts_oi", "put_oi", "pe_open_interest", "pe_oi"], "Put OI")
        
        # Extract Underlying Price (usually in the first row or metadata)
        # Note: nselib sometimes puts it in a separate 'underlyingValue' column
        underlying_col = None
        for name in ["underlyingvalue", "underlying_price", "underlying"]:
            if name in df.columns:
                underlying_col = name
                break

        if underlying_col:
            current_price = float(df[underlying_col].iloc[0])
        else:
            # Fallback: Get price from capital market if missing in options data
            quote = capital_market.price_volume_and_deliverable_position_data(symbol, period='1M')
            current_price = float(quote['ClosePrice'].iloc[-1])

        # 2. FILTER FOR NEAREST EXPIRY
        # Convert expiry dates to datetime objects to find the nearest one
        df['Expiry_DT'] = pd.to_datetime(df[expiry_col], errors='coerce', dayfirst=False)
        today = datetime.now()
        
        # Filter only future expiries
        future_expiries = df[df['Expiry_DT'] >= today]
        if future_expiries.empty:
            print("No future expiries found.")
            return

        nearest_expiry = future_expiries['Expiry_DT'].min()
        expiry_str = nearest_expiry.strftime('%d-%b-%Y')
        
        # Filter data for this expiry
        odo = df[df['Expiry_DT'] == nearest_expiry].copy()
        if odo.empty:
            print("No data available for the nearest expiry slice returned by NSE.")
            return
        
        print(f"Current Price:  ₹{current_price}")
        print(f"Expiry Selected:{expiry_str}")
        print("-" * 30)

        # --- STEP 1: Volatility & Range ---
        # Find ATM Strike
        strikes = odo[strike_col].astype(float).values
        atm_strike = strikes[(np.abs(strikes - current_price)).argmin()]
        
        # Get ATM IV (Average of CE and PE IV)
        atm_row = odo[odo[strike_col] == atm_strike].iloc[0]
        atm_iv = (float(atm_row[ce_iv_col]) + float(atm_row[pe_iv_col])) / 2
        
        # Calculate Range
        daily_range = current_price * (atm_iv / 100) * 0.063
        upper_band = current_price + daily_range
        lower_band = current_price - daily_range

        print(f"### STEP 1: Volatility (The Math)")
        print(f"ATM Strike:     {atm_strike}")
        print(f"ATM IV:         {atm_iv:.2f}%")
        print(f"Daily Range:    ₹{daily_range:.2f} (Swing: {lower_band:.1f} - {upper_band:.1f})")
        print("-" * 30)

        # --- STEP 2: Volume & Sentiment ---
        # Getting Delivery % requires a different call, skipping for speed in this script
        # We will focus on Option Structure which is the main "Trap" indicator
        
        # --- STEP 3 & 4: Live Levels (Trap Check) ---
        print(f"### STEP 4: Live Confirmation (The Levels)")
        
        # Identify Max OI for Support/Resistance
        # Ensure numeric conversion
        odo['CE_Open_Interest'] = pd.to_numeric(odo[call_oi_col], errors='coerce').fillna(0)
        odo['PE_Open_Interest'] = pd.to_numeric(odo[put_oi_col], errors='coerce').fillna(0)
        
        max_call_oi_row = odo.loc[odo['CE_Open_Interest'].idxmax()]
        max_put_oi_row = odo.loc[odo['PE_Open_Interest'].idxmax()]
        
        res_strike = max_call_oi_row[strike_col]
        sup_strike = max_put_oi_row[strike_col]
        
        # Calculate Max Pain
        # Max Pain = Strike with minimum total loss for option writers
        min_loss = float('inf')
        max_pain = 0
        
        for strike in strikes:
            # Loss for Call Writers: Max(0, Price - Strike) * OI
            # Loss for Put Writers: Max(0, Strike - Price) * OI
            # We approximate 'Price' with the test strike to find expiry convergence
            
            call_loss = odo.apply(lambda x: max(0, strike - x[strike_col]) * x['CE_Open_Interest'], axis=1).sum()
            put_loss = odo.apply(lambda x: max(0, x[strike_col] - strike) * x['PE_Open_Interest'], axis=1).sum()
            
            total_loss = call_loss + put_loss
            if total_loss < min_loss:
                min_loss = total_loss
                max_pain = strike

        print(f"Support (Put OI):    ₹{sup_strike}")
        print(f"Resistance (Call OI):₹{res_strike}")
        print(f"Max Pain:            ₹{max_pain}")
        
        # Verdict
        print("\n" + "=" * 30)
        signal = "WAIT / NEUTRAL"
        if current_price > max_pain and current_price > res_strike:
            signal = "BREAKOUT BUY 🟢"
        elif current_price < max_pain and current_price < sup_strike:
            signal = "BREAKDOWN SELL 🔴"
        elif abs(current_price - res_strike) < (current_price * 0.01):
            signal = "TRAP WARNING (At Resistance) ⚠️"
        
        print(f"FINAL VERDICT: {signal}")
        print("=" * 30)

    except Exception as e:
        print(f"Error: {e}")
        print("Tip: If nselib fails, try the 'Browser Console' method I shared previously.")

if __name__ == "__main__":
    get_live_trap_check(SYMBOL)
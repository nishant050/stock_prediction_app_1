# Stock Prediction Lab v2.0 - Advanced Analysis Engine

A comprehensive web application for Indian stock market analysis with multi-factor prediction engine, institutional flow tracking, and AI-powered insights.

## 🚀 Version 2.0 Features

### Advanced Analysis (New!)
- **FII/DII Flow Analysis**: Track institutional activity and Long/Short ratios
- **Central Pivot Range (CPR)**: Daily pivot levels with trend prediction
- **IV Range Calculation**: Statistical price range based on implied volatility  
- **OI 4-Quadrant Matrix**: Long Buildup, Short Buildup, Long Unwinding, Short Covering
- **VWAP Analysis**: Volume-weighted average price positioning
- **Gann Square of 9**: Mathematical support/resistance levels
- **Relative Strength**: Stock performance vs Nifty 50
- **Multi-Factor Prediction**: 9-factor weighted scoring system

### Core Features
- **Auto-Fetch Data**: Enter a stock symbol and automatically get:
  - Live option chain data from NSE
  - ATM Implied Volatility (IV)
  - Support & Resistance levels (from Max OI)
  - Max Pain calculation
  - Put-Call Ratio (PCR)
  - Delivery volume percentage
  
- **Intelligent Predictions**: Automated prediction engine with checklist-based scoring

- **AI Assistant**: Integrated GROQ AI to:
  - Generate comprehensive analysis reports
  - Answer questions about the analysis
  - Provide risk factors and trading insights

## 📁 Files

### v2.0 (Recommended)
- `app_advanced.py` - Advanced Flask backend with all new features
- `index_advanced.html` - Modern UI with complete analysis dashboard
- `start_advanced.bat` - Quick start for Windows

### v1.0 (Basic)
- `app.py` - Basic Flask backend server
- `index.html` - Basic frontend
- `start_server.bat` - Quick start for basic version

### Reference
- `backend.py` - Original standalone analysis script
- `frontend.html` - Original frontend template

## ⚡ Quick Start

### 1. Install Dependencies

```bash
pip install flask flask-cors nselib pandas numpy xlrd openpyxl
```

### 2. Start the Advanced Server

**Option A: Double-click** `start_advanced.bat`

**Option B: Command line**
```bash
python app_advanced.py
```

The server will start at `http://localhost:5000`

### 3. Open the Frontend

Simply open `index_advanced.html` in your browser, or use a local server:

```bash
# Option 1: Direct browser opening (Windows)
start index_advanced.html

# Option 2: Python HTTP server
python -m http.server 8000
# Then open http://localhost:8000/index_advanced.html
```

## 📊 Usage

1. **Start the backend**: Run `python app_advanced.py` or double-click `start_advanced.bat`
2. **Open the frontend**: Open `index_advanced.html` in browser
3. **Enter stock symbol**: e.g., RELIANCE, TCS, WIPRO, INFY
4. **Click Analyze**: All data is automatically fetched (takes 10-15 seconds)
5. **Review results**: 
   - Main prediction card with confidence score
   - Analysis checklist showing all 9 factors
   - FII/DII activity and market overview
   - CPR, Gann, and OI levels
6. **Ask AI**: Use GROQ AI to get detailed explanations

## ⚙️ Settings

Click the **Settings** button to configure:

- **GROQ API Key**: Your GROQ API key for AI explanations (pre-filled with default)
- **Model Selection**: Choose from various GROQ models:
  - Llama 3.3 70B (Versatile) - Best quality
  - Llama 3.1 8B (Fast) - Fastest response
  - Mixtral 8x7B - Good balance
  - Gemma 2 9B - Alternative option
- **Backend URL**: URL of your Flask server (default: http://localhost:5000)

## 🔌 API Endpoints (v2.0)

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Health check with version info |
| `GET /api/fii-dii` | FII/DII activity and Long/Short ratios |
| `GET /api/market-overview` | Nifty 50 overview with CPR levels |
| `GET /api/analyze/<symbol>` | Advanced stock analysis with all indicators |
| `GET /api/full-analysis/<symbol>` | Complete analysis with prediction checklist |

## 📈 Prediction Algorithm (v2.0)

The prediction uses a **9-factor weighted scoring system** (100 total points):

| Factor | Weight | Description |
|--------|--------|-------------|
| FII Activity | 15 | Institutional flow and Long/Short ratio |
| Market Gap | 10 | Nifty gap up/down analysis |
| Price vs CPR | 12 | Position relative to Central Pivot Range |
| Price vs VWAP | 10 | Above/Below Volume Weighted Average |
| OI Analysis | 18 | 4-Quadrant Matrix interpretation |
| PCR | 10 | Put-Call Ratio sentiment |
| IV Range | 8 | Mean reversion signals |
| Delivery | 12 | Genuine vs speculative moves |
| Relative Strength | 5 | Performance vs Nifty 50 |

### Prediction Output
- **BULLISH**: Bullish score > Bearish score × 1.3
- **BEARISH**: Bearish score > Bullish score × 1.3
- **NEUTRAL**: Mixed signals

### Action Recommendations
- **BUY**: Bullish prediction with ≥5 checklist passes
- **SELL**: Bearish prediction with ≥5 checklist fails
- **WAIT**: Neutral prediction
- **CAUTION**: Some confirmations but low conviction

## 📋 Analysis Checklist

Each factor can have the following status:
- ✅ **PASS**: Bullish confirmation
- ❌ **FAIL**: Bearish confirmation
- ⚠️ **WARN**: Caution signal
- ⚪ **NEUTRAL**: No clear signal
- ⭕ **N/A**: Data unavailable

## 🔧 Troubleshooting

### Backend not connecting
- Ensure `app_advanced.py` is running
- Check if port 5000 is available
- Verify the backend URL in Settings

### NSE data fetch fails
- NSE may rate-limit requests; wait a few seconds
- Market hours (9:15 AM - 3:30 PM) have most reliable data
- Some stocks may not have F&O data

### FII/DII data unavailable
- Data is published after market hours
- Try again after 6 PM IST

## 📝 License

For personal use only. NSE data belongs to National Stock Exchange of India.

## ⚠️ Disclaimer

This tool is for educational purposes only. Always do your own research before trading. Past performance does not guarantee future results.

### AI not responding
- Check GROQ API key in Settings
- Verify internet connection
- Try a different model

## Disclaimer

⚠️ **This tool is for educational purposes only.** 

- Not financial advice
- Always do your own research
- Past patterns don't guarantee future results
- Markets are inherently unpredictable

## License

MIT License - Feel free to modify and use as needed.

## 🔐 Security & API Keys

- Do NOT commit private API keys or secrets to this repository. The frontend used to include a default GROQ API key; this has been removed. Set your key in the Settings modal instead (saved in localStorage), or configure server-side access for production.
- For production deployments, it is recommended to keep secrets on the server and configure a server-side API proxy that performs AI calls—this avoids exposing keys in client-side code. This repository ships a simple proxy endpoint at `/api/ai/chat` in `app_advanced.py`; set `GROQ_API_KEY` as an environment variable on your server and call this endpoint from the frontend instead of calling GROQ directly.
  - The frontend also provides a Settings option to use the server-side proxy or to call GROQ directly from the browser (not recommended). The proxy will be used by default.

## 🧪 Testing & CI

- This repository includes a basic Pytest test to validate the Flask health endpoint. To run tests locally:

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
pytest -q
```

- GitHub Actions CI workflow is included at `.github/workflows/python-app.yml` and will run tests and flake8 on push/PR.

## ✅ Quick checklist before pushing to GitHub

1. Remove any personal or secret keys from the codebase. Use environment variables instead.
2. Check `.gitignore` to ensure local files and artifacts are not committed.
3. Run `pytest` locally and confirm tests pass.
4. Commit and push; GitHub Actions will run the CI workflow.

If you want, I can also add a server-side environment variable loader and an example `.env.example` file to show how to configure GROQ keys and other secrets securely.

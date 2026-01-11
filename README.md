# Wise Dashboard

A Python project that fetches Wise account balances regularly and displays them in Grafana using InfluxDB.

## Features

- Fetches account balances from Wise API every hour (STANDARD and SAVINGS types)
- For SAVINGS balances: captures total returns (as shown in Wise UI) when available
- Stores balance data in InfluxDB with proper tags and fields
- Visualizes data in Grafana dashboards
- Supports multiple Wise profiles
- Tracks balances by currency and balance type over time

## Prerequisites

- Python 3.8+
- Wise API token stored at `~/creds/wise_personal_account_token`
- InfluxDB installed and running
- Grafana installed and running

## Setup

### 1. Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Load the Wise token from the credentials file:

```bash
source setup_env.sh
```

Or manually:

```bash
export WISE_TOKEN=$(cat ~/creds/wise_personal_account_token)
```

### 3. Configure InfluxDB

Set up InfluxDB environment variables (optional, defaults shown):

```bash
export INFLUXDB_URL="http://localhost:8181"  # InfluxDB v3 uses port 8181
export INFLUXDB_TOKEN="your-influxdb-token"
export INFLUXDB_ORG="my-org"
export INFLUXDB_BUCKET="wise_balances"
```

Create the bucket in InfluxDB:

```bash
influx bucket create -n wise_balances -o my-org
```

### 4. Test the Script

Run the balance fetcher manually:

```bash
source setup_env.sh
python fetch_balances.py
```

## Scheduling

### Option 1: Cron (Recommended)

Add to your crontab (`crontab -e`):

```bash
# Run every hour
0 * * * * cd /Users/lbodor/repos/wise_dashboard && source setup_env.sh && /Users/lbodor/repos/wise_dashboard/venv/bin/python fetch_balances.py >> /tmp/wise_balances.log 2>&1
```

### Option 2: Python Scheduler

Use a Python scheduler like `schedule` library (not included, install separately):

```bash
pip install schedule
python scheduler.py  # Run continuously
```

## Grafana Setup

1. **Add InfluxDB Data Source:**
   - Go to **Configuration** → **Data Sources** → **Add data source** → **InfluxDB**
   - **URL**: `http://localhost:8181` (IMPORTANT: Use `http://` NOT `https://`, port 8181 for InfluxDB v3)
   - **Access**: Server (default)
   - **Organization**: `my-org` (or your org name)
   - **Token**: Your InfluxDB token (the one created earlier: `apiv3_...`)
   - **Database/Bucket**: `wise_balances`
   - **Query Language**: Select **SQL** (InfluxDB v3 works better with SQL)
   - **Important**: Do NOT enable SSL/TLS options
   - Click **Save & Test** - should show "Data source is working"
   
   **Common Error Fix**: If you see "TLS handshake failed", make sure:
   - URL uses `http://` not `https://`
   - No SSL/TLS certificates are configured
   - Port is `8181` not `8086`

2. **Import Dashboard:**
   - Go to Grafana → Dashboards → Import
   - Upload the `grafana_dashboard.json` file
   - Select your InfluxDB data source
   - The dashboard will automatically configure queries for your data

2. **Dashboard Queries (SQL):**
   
   The dashboard uses SQL queries. Here are example SQL queries you can use:
   
   **Total Balance in HUF:**
   ```sql
   SELECT time, total_balance_huf 
   FROM wise_total_balance_huf 
   WHERE time >= $__timeFrom() AND time <= $__timeTo()
   ORDER BY time
   ```
   
   **All Balances:**
   ```sql
   SELECT time, currency, total_worth 
   FROM wise_balance 
   WHERE time >= $__timeFrom() AND time <= $__timeTo()
   ORDER BY time
   ```
   
   **USD Balances Only:**
   ```sql
   SELECT time, currency, total_worth 
   FROM wise_balance 
   WHERE time >= $__timeFrom() AND time <= $__timeTo() 
     AND currency = 'USD'
   ORDER BY time
   ```
   
   **Savings Balances with Returns:**
   ```sql
   SELECT time, currency, total_worth, total_returns 
   FROM wise_balance 
   WHERE time >= $__timeFrom() AND time <= $__timeTo() 
     AND balance_type = 'SAVINGS'
   ORDER BY time
   ```
   
   **Current Balances:**
   ```sql
   SELECT currency, balance_type, total_worth 
   FROM wise_balance 
   WHERE time >= NOW() - INTERVAL '1 hour'
   ORDER BY time DESC
   ```

## Project Structure

```
wise_dashboard/
├── fetch_balances.py      # Main script to fetch and store balances
├── setup_env.sh           # Environment setup script
├── requirements.txt       # Python dependencies
├── grafana_dashboard.json # Grafana dashboard configuration (importable)
├── README.md             # This file
└── .gitignore            # Git ignore rules
```

## Wise API

This project uses the Wise TransferWise API:
- Profiles endpoint: `/v1/profiles`
- Balances endpoint: `/v3/profiles/{id}/balances`

Make sure your API token has the necessary permissions to read balances.

## Troubleshooting

- **WISE_TOKEN not found:** Ensure `~/creds/wise_personal_account_token` exists and contains your token
- **InfluxDB connection error:** Verify InfluxDB is running and credentials are correct
- **API errors:** Check your Wise API token permissions and validity

## License

MIT

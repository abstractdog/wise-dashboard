#!/usr/bin/env python3
"""
Wise Balance Fetcher

Fetches account balances (STANDARD and SAVINGS) from Wise API 
and stores them in InfluxDB.
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS


class WiseBalanceFetcher:
    def __init__(self, wise_token: str, influx_url: str, influx_token: str, 
                 influx_org: str, influx_bucket: str):
        self.wise_token = wise_token
        self.influx_url = influx_url
        self.influx_token = influx_token
        self.influx_org = influx_org
        self.influx_bucket = influx_bucket
        
        # Try v4 API first (api.wise.com), fallback to v1/v3 (api.transferwise.com)
        self.wise_base_url = os.getenv('WISE_API_BASE_URL', 'https://api.wise.com')
        self.headers = {
            'Authorization': f'Bearer {self.wise_token}',
            'Content-Type': 'application/json'
        }
    
    def get_profiles(self):
        """Fetch all profiles from Wise API."""
        # Try v4 API first
        endpoints = [
            f'{self.wise_base_url}/v4/profiles',
            f'https://api.transferwise.com/v1/profiles'
        ]
        
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, headers=self.headers)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException:
                continue
        
        raise Exception("Failed to fetch profiles from all API endpoints")
    
    def get_exchange_rate(self, from_currency: str, to_currency: str = 'HUF'):
        """Get exchange rate from Wise API or fallback to free API."""
        if from_currency == to_currency:
            return 1.0
        
        # Try Wise API first
        endpoints = [
            f'{self.wise_base_url}/v1/rates?source={from_currency}&target={to_currency}',
            f'https://api.transferwise.com/v1/rates?source={from_currency}&target={to_currency}'
        ]
        
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, headers=self.headers)
                if response.status_code == 200:
                    data = response.json()
                    # Wise API might return rate in different formats
                    if isinstance(data, list) and len(data) > 0:
                        rate = data[0].get('rate', 0)
                        if rate:
                            return float(rate)
                    elif isinstance(data, dict):
                        rate = data.get('rate') or data.get('exchangeRate', 0)
                        if rate:
                            return float(rate)
            except requests.exceptions.RequestException:
                continue
        
        # Fallback to free exchange rate API
        try:
            # Using exchangerate-api.com (free, no API key needed)
            response = requests.get(
                f'https://api.exchangerate-api.com/v4/latest/{from_currency}',
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                rates = data.get('rates', {})
                if to_currency in rates:
                    return float(rates[to_currency])
        except Exception:
            pass
        
        # If all fails, return 0 (will skip this currency)
        print(f"  Warning: Could not fetch exchange rate for {from_currency} to {to_currency}", file=sys.stderr)
        return 0.0
    
    def get_balances(self, profile_id: int, balance_types: list = None):
        """Fetch balances for a specific profile.
        
        Args:
            profile_id: Profile ID
            balance_types: List of balance types to fetch. Options include:
                - 'STANDARD': Standard account balances
                - 'SAVINGS': Savings account balances
                Defaults to ['STANDARD', 'SAVINGS'] if None.
        """
        if balance_types is None:
            balance_types = ['STANDARD', 'SAVINGS']
        
        all_balances = []
        
        for balance_type in balance_types:
            # Try v4 API first
            endpoints = [
                (f'{self.wise_base_url}/v4/profiles/{profile_id}/balances', {'types': balance_type}),
                (f'https://api.transferwise.com/v3/profiles/{profile_id}/balances', {'types': balance_type})
            ]
            
            for endpoint, params in endpoints:
                try:
                    response = requests.get(endpoint, headers=self.headers, params=params)
                    response.raise_for_status()
                    balances = response.json()
                    if isinstance(balances, list):
                        # Mark each balance with its type
                        for balance in balances:
                            balance['balance_type'] = balance_type
                        all_balances.extend(balances)
                    break
                except requests.exceptions.RequestException:
                    continue
        
        return all_balances if all_balances else None
    
    def write_to_influxdb(self, data_points: list):
        """Write data points to InfluxDB."""
        if not data_points:
            return
        
        client = InfluxDBClient(
            url=self.influx_url,
            token=self.influx_token,
            org=self.influx_org
        )
        
        write_api = client.write_api(write_options=SYNCHRONOUS)
        
        try:
            write_api.write(bucket=self.influx_bucket, org=self.influx_org, record=data_points)
            print(f"Successfully wrote {len(data_points)} points to InfluxDB")
        except Exception as e:
            print(f"Error writing to InfluxDB: {e}", file=sys.stderr)
            raise
        finally:
            client.close()
    
    def write_balances_to_influxdb(self, balances: list, profile_id: int, profile_type: str = None):
        """Write balance data to InfluxDB."""
        points = []
        timestamp = datetime.now(timezone.utc)
        
        for balance in balances:
            currency = balance.get('currency', 'UNKNOWN')
            
            # Use totalWorth if available, otherwise fall back to amount
            total_worth_value = None
            total_worth_currency = currency
            if 'totalWorth' in balance:
                total_worth = balance['totalWorth']
                if isinstance(total_worth, dict):
                    total_worth_value = total_worth.get('value', 0)
                    total_worth_currency = total_worth.get('currency', currency)
                else:
                    total_worth_value = total_worth
            
            # Fallback to amount if totalWorth not available
            if total_worth_value is None:
                amount_obj = balance.get('amount', {})
                if isinstance(amount_obj, dict):
                    total_worth_value = amount_obj.get('value', 0)
                    total_worth_currency = amount_obj.get('currency', currency)
                else:
                    total_worth_value = amount_obj if amount_obj else 0
            
            balance_type = balance.get('balance_type', 'STANDARD')
            
            # Create a data point
            # Note: profile_id is stored as a tag (for efficient filtering and grouping)
            # Tags: currency, balance_type, profile_id (for filtering and grouping in queries)
            # Fields: total_worth, total_worth_currency (the actual data values)
            point = Point("wise_balance") \
                .tag("currency", currency) \
                .tag("balance_type", balance_type) \
                .tag("profile_id", str(profile_id)) \
                .field("total_worth", float(total_worth_value)) \
                .field("total_worth_currency", total_worth_currency) \
                .time(timestamp)
            
            # Also store amount field if it exists (for backward compatibility)
            amount_obj = balance.get('amount', {})
            if amount_obj:
                if isinstance(amount_obj, dict):
                    amount_value = amount_obj.get('value', 0)
                else:
                    amount_value = amount_obj
                if amount_value != total_worth_value:  # Only add if different
                    point.field("amount", float(amount_value))
            
            if profile_type:
                point.tag("profile_type", profile_type)
            
            # Add interest field if present
            if 'interest' in balance:
                point.field("interest", float(balance['interest']))
            
            # For SAVINGS balances, capture total returns if available
            if balance_type == 'SAVINGS':
                if 'returns' in balance:
                    point.field("total_returns", float(balance['returns']))
            
            points.append(point)
        
        if points:
            self.write_to_influxdb(points)
    
    def write_total_balance_huf_to_influxdb(self, total_balance_huf: float):
        """Write total balance in HUF to InfluxDB."""
        timestamp = datetime.now(timezone.utc)
        
        point = Point("wise_total_balance_huf") \
            .tag("currency", "HUF") \
            .field("total_balance_huf", float(total_balance_huf)) \
            .time(timestamp)
        
        self.write_to_influxdb([point])
    
    def write_exchange_rate_to_influxdb(self, from_currency: str, to_currency: str, rate: float):
        """Write exchange rate to InfluxDB."""
        timestamp = datetime.now(timezone.utc)
        
        point = Point("exchange_rate") \
            .tag("from_currency", from_currency) \
            .tag("to_currency", to_currency) \
            .field("rate", float(rate)) \
            .time(timestamp)
        
        self.write_to_influxdb([point])
    
    def fetch_and_store(self):
        """Main method to fetch all balances (STANDARD and SAVINGS)."""
        try:
            # Fetch Wise data
            profiles = self.get_profiles()
            print(f"Found {len(profiles)} profile(s)")
            
            # Collect all balances for total calculation
            all_balances = []
            
            for profile in profiles:
                profile_id = profile['id']
                profile_type = profile.get('type', 'UNKNOWN')
                
                print(f"\nProcessing profile {profile_id} (type: {profile_type})")
                
                # Fetch STANDARD and SAVINGS balances
                print("  Fetching balances...")
                balances = self.get_balances(profile_id)
                if balances:
                    # Store balances for total calculation
                    all_balances.extend(balances)
                    
                    self.write_balances_to_influxdb(balances, profile_id, profile_type)
                    print(f"  Found {len(balances)} balance(s)")
                    for balance in balances:
                        currency = balance.get('currency', 'UNKNOWN')
                        
                        # Get totalWorth if available, otherwise use amount
                        total_worth = None
                        if 'totalWorth' in balance:
                            total_worth_obj = balance['totalWorth']
                            if isinstance(total_worth_obj, dict):
                                total_worth = total_worth_obj.get('value', 0)
                            else:
                                total_worth = total_worth_obj
                        
                        if total_worth is None:
                            amount_obj = balance.get('amount', {})
                            if isinstance(amount_obj, dict):
                                total_worth = amount_obj.get('value', 0)
                            else:
                                total_worth = amount_obj if amount_obj else 0
                        
                        balance_type = balance.get('balance_type', 'STANDARD')
                        output = f"    {balance_type} - {currency}: {total_worth}"
                        
                        # Display total returns for savings if available
                        if balance_type == 'SAVINGS' and 'returns' in balance:
                            try:
                                returns_val = float(balance['returns'])
                                output += f" (Total Returns: {returns_val:.2f} {currency})"
                            except (ValueError, TypeError):
                                pass
                        
                        print(output)
                else:
                    print(f"  No balances found for profile {profile_id}")
            
            # Calculate total balance in HUF
            if all_balances:
                print("\nCalculating total balance in HUF...")
                total_balance_huf = 0.0
                exchange_rates_cache = {}  # Cache exchange rates
                
                for balance in all_balances:
                    currency = balance.get('currency', 'UNKNOWN')
                    
                    # Get totalWorth if available, otherwise use amount
                    total_worth = None
                    if 'totalWorth' in balance:
                        total_worth_obj = balance['totalWorth']
                        if isinstance(total_worth_obj, dict):
                            total_worth = total_worth_obj.get('value', 0)
                        else:
                            total_worth = total_worth_obj
                    
                    if total_worth is None:
                        amount_obj = balance.get('amount', {})
                        if isinstance(amount_obj, dict):
                            total_worth = amount_obj.get('value', 0)
                        else:
                            total_worth = amount_obj if amount_obj else 0
                    
                    try:
                        balance_value = float(total_worth)
                        
                        # Convert to HUF
                        if currency == 'HUF':
                            converted_value = balance_value
                        else:
                            # Get exchange rate (use cache if available)
                            if currency not in exchange_rates_cache:
                                print(f"  Fetching exchange rate: {currency} -> HUF")
                                exchange_rates_cache[currency] = self.get_exchange_rate(currency, 'HUF')
                            
                            rate = exchange_rates_cache[currency]
                            if rate > 0:
                                converted_value = balance_value * rate
                                print(f"    {currency} {balance_value:.2f} -> HUF {converted_value:.2f} (rate: {rate})")
                                # Store exchange rate in InfluxDB
                                self.write_exchange_rate_to_influxdb(currency, 'HUF', rate)
                            else:
                                print(f"    Warning: Skipping {currency} {balance_value:.2f} (no exchange rate)")
                                converted_value = 0
                        
                        total_balance_huf += converted_value
                    except (ValueError, TypeError) as e:
                        print(f"    Warning: Could not convert balance: {e}", file=sys.stderr)
                
                # Store total balance in HUF
                if total_balance_huf > 0:
                    print(f"\nTotal balance in HUF: {total_balance_huf:.2f}")
                    self.write_total_balance_huf_to_influxdb(total_balance_huf)
                
                # Always store USD/HUF and EUR/HUF exchange rates (even if no balance in those currencies)
                for track_currency in ['USD', 'EUR']:
                    if track_currency not in exchange_rates_cache:
                        print(f"  Fetching {track_currency} -> HUF exchange rate for tracking...")
                        rate = self.get_exchange_rate(track_currency, 'HUF')
                        if rate > 0:
                            self.write_exchange_rate_to_influxdb(track_currency, 'HUF', rate)
                            print(f"  {track_currency}/HUF rate: {rate:.2f}")
            
            print("\nBalance fetch completed successfully")
            return True
            
        except Exception as e:
            print(f"Error in fetch_and_store: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return False


def main():
    """Main entry point."""
    # Get environment variables
    wise_token = os.getenv('WISE_TOKEN')
    if not wise_token:
        print("Error: WISE_TOKEN environment variable is not set", file=sys.stderr)
        print("Please ensure the token is loaded from ~/creds/wise_personal_account_token", file=sys.stderr)
        sys.exit(1)
    
    # InfluxDB configuration (can be overridden via environment variables)
    # Note: InfluxDB v3 uses port 8181 by default (not 8086)
    influx_url = os.getenv('INFLUXDB_URL', 'http://localhost:8181')
    influx_token = os.getenv('INFLUXDB_TOKEN', '')
    influx_org = os.getenv('INFLUXDB_ORG', 'my-org')
    influx_bucket = os.getenv('INFLUXDB_BUCKET', 'wise_balances')
    
    # Create fetcher and run
    fetcher = WiseBalanceFetcher(
        wise_token=wise_token,
        influx_url=influx_url,
        influx_token=influx_token,
        influx_org=influx_org,
        influx_bucket=influx_bucket
    )
    
    success = fetcher.fetch_and_store()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

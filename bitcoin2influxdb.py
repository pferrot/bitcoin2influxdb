import argparse
import csv
import json
import logging
import os.path
import requests
import sys
import time
from datetime import datetime
from datetime import timedelta
from influxdb_client import InfluxDBClient, Point, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS

influxdb_url_default = 'http://localhost:8086'
influxdb_token_default = 'my-super-secret-auth-token'
influxdb_org_default = 'my-org'
influxdb_bucket_default = 'bitcoin'
influxdb_write_api = None
influxdb_org = None
influxdb_bucket = None
influxdb_batch_size = 10
influxdb_flush_interval_ms = 10_0000
influxdb_batch = []

cache_folder = 'cache'
sats_to_btc = 100_000_000

timestamp_field = "ts"

previous_for_wallet = {}

logger = logging.getLogger("sat.computedevents")
logging.basicConfig(level=logging.WARNING)

def str2bool(v):
    """Return the Boolean value corresponding to a String.
    'yes', 'true', 't', 'y', '1' (case insensitive) will return True.
    'no', 'false', 'f', 'n', '0' (case insensitive) will return false.
    Any other value will raise a argparse.ArgumentTypeError.
    """
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

# date like "2020-07-02T13:07:06+02:00"
#def get_datetime(time_str):
    # See https://stackoverflow.com/a/12282040/9540480
#    return datetime.strptime(''.join(time_str.rsplit(':', 1)), '%Y-%m-%dT%H:%M:%S%z')

# Unix-like timestamp, i.e. seconds since Epoch. E.g. "1601589661.577838".
def get_datetime_from_timestamp(timestamp):
    if type(timestamp) is float or type(timestamp) is int:
        return datetime.utcfromtimestamp(timestamp)
    elif is_float(timestamp):
        return datetime.utcfromtimestamp(float(timestamp))

def get_date_iso_format(datetime):
    r = datetime.isoformat("T").replace("+00:00", "Z")

    if not r.endswith("Z"):
        r = r + "Z"

    return r

def is_float(s):
    if not s:
        return False
    else:
        return re.match(r'^-?\d+(?:\.\d+)?(?:[Ee]-?\d+)?$', s)

def get_timestamps_array(start_timestamp, end_timestamp):
    start_datetime = datetime.fromisoformat(start_timestamp.replace("Z", "+00:00"))
    end_datetime = datetime.fromisoformat(end_timestamp.replace("Z", "+00:00"))

    if end_datetime <= start_datetime:
        return []

    result = []
    next_hour = None
    one_hour = timedelta(hours=1)
    while not next_hour or next_hour <= end_datetime :
        if next_hour:
            next_hour = next_hour + one_hour
        else:
            next_hour = start_datetime.replace(minute=0, second=0, microsecond=0)
            # If the start date is at the top of the hour, include it.
            if next_hour < start_datetime:
                next_hour = next_hour + one_hour

        result.append(get_date_iso_format(next_hour))

    return result

def fill_timestamps(timestamps, balance, wallet):
    global influxdb_write_api
    global influxdb_org
    global influxdb_bucket
    for t in timestamps:
        record = {
            "fields": {
                "balance": balance,
            },
            "measurement": "bitcoin",
            "tags": {
                "wallet": wallet,
                "type": "hourly"
            },
            "time": t
        }
        #print("Writing hour record %s" % json.dumps(record, indent = 4, sort_keys = True))
        influxdb_write_api.write(influxdb_bucket, influxdb_org, record)

def publish_to_influxdb(batch):
    global influxdb_write_api
    global influxdb_org
    global influxdb_bucket
    global previous_for_wallet

    for i in batch:
        #print("Writing %s" % json.dumps(i, indent = 4, sort_keys = True))
        influxdb_write_api.write(influxdb_bucket, influxdb_org, i)

        if "wallet" in i["tags"]:
            wallet = i["tags"]["wallet"]
            # Arbitrary date, add 0 balance since then until first actuals sats.
            previous_timestamp = "2017-01-01T00:00:00Z"
            # Genesis block.
            #previous_timestamp = "2009-01-03T18:15:05Z"
            balance = 0
            current_timestamp = i["time"]
            if wallet in previous_for_wallet:
                balance = i["fields"]["balance"]
                previous_timestamp = previous_for_wallet[wallet]["time"]

            timestamps = get_timestamps_array(previous_timestamp, current_timestamp)
            fill_timestamps(timestamps=timestamps, balance=balance, wallet=wallet)

            previous_for_wallet[wallet] = i



def process_operation(txid, amount, fee, balance, wallet, timestamp_epoch_seconds):
    global influxdb_batch
    global influxdb_batch_size
    global latest_timestamp_published
    global latest_timestamp_read

    timestamp = get_date_iso_format(get_datetime_from_timestamp(timestamp_epoch_seconds))

    fields = {
        "amount": amount,
        "fee": fee,
        "balance": balance
    }

    tags = {
        "txid": txid,
        "wallet": wallet
    }

    j = {
        "measurement": "bitcoin",
        "tags": tags,
        "time": timestamp,
        "fields": fields
    }

    influxdb_batch.append(j)

    if len(influxdb_batch) >= influxdb_batch_size:
        publish_to_influxdb(influxdb_batch)
        print("Published %d operations to InfluxDB" % (len(influxdb_batch)))
        influxdb_batch = []


def process_btc_price(price_usd, timestamp_iso_format, source):
    global influxdb_batch
    global influxdb_batch_size
    global latest_timestamp_published
    global latest_timestamp_read

    fields = {
        "btc_price_usd": price_usd
    }

    tags = {
        "source": source
    }

    j = {
        "measurement": "bitcoin",
        "tags": tags,
        "time": timestamp_iso_format,
        "fields": fields
    }

    influxdb_batch.append(j)

    if len(influxdb_batch) >= influxdb_batch_size:
        publish_to_influxdb(influxdb_batch)
        print("Published %d BTC prices to InfluxDB" % (len(influxdb_batch)))
        influxdb_batch = []

def process_usd_to_chf(exchange_rate, timestamp_iso_format):
    global influxdb_batch
    global influxdb_batch_size
    global latest_timestamp_published
    global latest_timestamp_read

    fields = {
        "usd_chf": exchange_rate
    }

    tags = {
    }

    j = {
        "measurement": "bitcoin",
        "tags": tags,
        "time": timestamp_iso_format,
        "fields": fields
    }

    influxdb_batch.append(j)

    if len(influxdb_batch) >= influxdb_batch_size:
        publish_to_influxdb(influxdb_batch)
        print("Published %d exchange rates to InfluxDB" % (len(influxdb_batch)))
        influxdb_batch = []


def get_tx_json(txid):
    r = requests.get('https://blockstream.info/api/tx/%s' % txid)
    if r.status_code != 200:
        raise Exception("Unexpected response code when retriving transaction: %d" % r.status_code)

    return r.json()

def get_filename_with_path(filename, folder):
    """Returns the filename with path, given the base filename and folder.
    """
    return "%s%s%s" % (folder, "" if folder.endswith("/") else "/", filename)

# def get_cache_filename(txid):
#     """Returns the filename of the cache file for a given txid.

#     The cache filename is the SHA1 of the GitHub URL used to retrieve the date, the files to be ignored
#     (although that feature is currently hidden/disabled) and the schema version.

#     Using a so called schema version allows to easily modify the data stored in the cache in future versions
#     as legacy cache files be ignored (because a different schema version will lead to a different
#     SHA1, i.e. different filename). This comes at the cost of having the fetch the data from GitHub again.
#     """
#     # Important to take args.ignore_files into account as the result depends on this parameter.
#     cache_filename = hashlib.sha1(("%s%s%d" % (url, ",".join(args.ignore_files) if args.ignore_files else "", m_schema_version)).encode('utf-8')).hexdigest()
#     #print("Cache filename: %s" % cache_filename)
#     return cache_filename

def get_tx_cache_filename_with_path(txid):
    """Returns the filename (with full path) of the cache file for a given txid.

    See get_cache_filename(url) for more details.
    """
    return get_filename_with_path("%s.json" % txid, cache_folder)

def cache_tx(txid, the_json):
    """Saves the given JSON in a local cache file (overwrites it if it exists already).
    """
    #print ("    Caching: %s" % url)
    with open(get_tx_cache_filename_with_path(txid), 'w') as outfile:
        json.dump(the_json, outfile)


def get_tx_from_cache(txid):
    """Returns the cache for a given txid.

    Returns None if no cache file exists.

    If an error occurs when reading the file, a message is logged and None is returned.
    """
    cache_file = get_tx_cache_filename_with_path(txid)
    if not os.path.exists(cache_file):
        print("    No cache (file does not exist: %s)" % cache_file)
        return None
    else:
        print("    Cache found (file: %s)" % cache_file)
        try:
            with open(cache_file) as json_data:
                return json.load(json_data)
        except:
            print("    Error loading cache from file %s, so ignoring file" % cache_file)
            return None


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Import Bitcoin transactions exported into InfluxDB.')

    file_group = parser.add_mutually_exclusive_group(required=True)
    file_group.add_argument('-llf', '--ledger_live_file', type=str, nargs='?', help='Path to Ledger Live CSV file')
    file_group.add_argument('-ef', '--electrum_file', type=str, nargs='?', help='Path to Electrum CSV file')
    file_group.add_argument('-cf', '--coinmarketcap_file', type=str, nargs='?', help='CoinMarketCap BTC price file')
    file_group.add_argument('-ucf', '--usd_chf_file', type=str, nargs='?', help='USD to CHF file')

    parser.add_argument('-iu', '--influxdb_url', type=str, nargs=1, required=False, help='InfluxDB URL, default: %s' % influxdb_url_default)
    parser.add_argument('-it', '--influxdb_token', type=str, nargs=1, required=False, help='InfluxDB token, default: %s' % influxdb_token_default)
    parser.add_argument('-io', '--influxdb_org', type=str, nargs=1, required=False, help='InfluxDB org, default: %s' % influxdb_org_default)
    parser.add_argument('-ib', '--influxdb_bucket', type=str, nargs=1, required=False, help='InfluxDB bucket, default: %s' % influxdb_bucket_default)
    parser.add_argument('-c', '--cache_folder', type=str, nargs='?', help='Folder where cache files are stored, default: %s' % cache_folder)

    args = parser.parse_args()

    influxdb_url = influxdb_url_default
    if args.influxdb_url:
        influxdb_url = args.influxdb_url[0]
    influxdb_token = influxdb_token_default
    if args.influxdb_token:
        influxdb_token = args.influxdb_token[0]
    influxdb_org = influxdb_org_default
    if args.influxdb_org:
        influxdb_org = args.influxdb_org[0]
    influxdb_bucket = influxdb_bucket_default
    if args.influxdb_bucket:
        influxdb_bucket = args.influxdb_bucket[0]

    ledger_live_file = None
    if args.ledger_live_file:
        ledger_live_file = args.ledger_live_file

    electrum_file = None
    if args.electrum_file:
        electrum_file = args.electrum_file

    coinmarketcap_file = None
    if args.coinmarketcap_file:
        coinmarketcap_file = args.coinmarketcap_file

    usd_chf_file = None
    if args.usd_chf_file:
        usd_chf_file = args.usd_chf_file

    if args.cache_folder:
        cache_folder = args.cache_folder

    print("bitcoin2influxdb")
    print("----------------\n")

    # Do not show entire conntection string as it container a secret.
    is_ledger_csv_file = False
    is_electrum_csv_file = False
    operations_csv_file = None
    if ledger_live_file:
        print("Path to Ledger Live CSV file: %s" % ledger_live_file)
        operations_csv_file = ledger_live_file
        is_ledger_csv_file = True
    if electrum_file:
        print("Path to Electrum CSV file: %s" % electrum_file)
        operations_csv_file = electrum_file
        is_electrum_csv_file = True
    if coinmarketcap_file:
        print("CoinMarketCap BTC price file: %s" % coinmarketcap_file)
    if usd_chf_file:
        print("USD to CHF file: %s" % usd_chf_file)

    print("Cache folder: %s" % cache_folder)
    print("InfluxDB URL: %s" % influxdb_url)
    print("InfluxDB org: %s" % influxdb_org)
    print("InfluxDB bucket: %s" % influxdb_bucket)
    print("")

    if not os.access(cache_folder, os.W_OK):
        print("ERROR: cache folder does not exist or is not writable: %s" % cache_folder)
        exit(1)

    with InfluxDBClient(url=influxdb_url, token=influxdb_token, org=influxdb_org) as influxdb_client:

        with influxdb_client.write_api(write_options=WriteOptions(batch_size=influxdb_batch_size, flush_interval=influxdb_flush_interval_ms)) as write_api:
        #with influxdb_client.write_api(write_options=SYNCHRONOUS) as write_api:

            influxdb_write_api = write_api

            if operations_csv_file:

                with open(operations_csv_file, newline='') as f:
                    reader = csv.reader(f, delimiter=',', quoting=csv.QUOTE_NONE)
                    rows = []
                    for row in reader:
                        rows.append(row)
                    # Skip header
                    rows = rows[1:]
                    rows.sort

                    def get_amount_ledger(row):
                        amount = float(row[3])
                        if row[2] == "OUT":
                            amount = -amount
                        return int(amount * sats_to_btc)

                    def get_amount_electrum(row):
                        return int(float(row[3]) * sats_to_btc)

                    def get_wallet_ledger(row, file_name):
                        return row[6]

                    def get_wallet_electrum(row, file_name):
                        return file_name[len("electrum-history-"):-len(".csv")]

                    if is_ledger_csv_file:
                        timestamp_index = 0
                        txid_index = 5
                        get_amount_func = get_amount_ledger
                        get_wallet_func = get_wallet_ledger
                    elif is_electrum_csv_file:
                        timestamp_index = 7
                        txid_index = 0
                        get_amount_func = get_amount_electrum
                        get_wallet_func = get_wallet_electrum
                    else:
                        raise Exception("Unsupported CSV file format")

                    # Sort by timestamp ascending.
                    rows = sorted(rows, key=lambda x: x[timestamp_index])

                    balances = {}

                    for row in rows:
                        txid = row[txid_index]
                        tx_json = get_tx_from_cache(txid)
                        if not tx_json:
                            tx_json = get_tx_json(txid)
                            cache_tx(txid, tx_json)
                        #print("Tx JSON: %s" % json.dumps(tx_json, indent = 4, sort_keys = True))

                        fee = tx_json["fee"]
                        block_time = tx_json["status"]["block_time"]
                        amount = get_amount_func(row)
                        wallet = get_wallet_func(row, operations_csv_file)
                        print("--------")
                        print("Txid: %s" % txid)
                        print("Amount: %d" % amount)
                        print("Fee: %d" % fee)
                        print("Wallet: %s" % wallet)
                        print("Block time: %d" % block_time)

                        balance = balances[wallet] if wallet in balances else 0
                        # Amount can be negative.
                        # Also, amount already includes fee for payments (out transactions).
                        balance = balance + amount
                        balances[wallet] = balance

                        print("Balance: %d" % balance)

                        process_operation(txid=txid, amount=amount, fee=fee, balance=balance, wallet=wallet, timestamp_epoch_seconds=block_time)

                if len(influxdb_batch) > 0:
                    print("Batch with %d operations left, publishing to InfluxDB." % len(influxdb_batch))
                    publish_to_influxdb(influxdb_batch)
                    influxdb_batch = []
                else:
                    print("Batch empty, nothing left to publish to InfluxDB")

                for wallet in previous_for_wallet:
                    print("Addding future hourly balances")
                    timestamps = get_timestamps_array(previous_for_wallet[wallet]["time"], "2025-01-01T00:00:00Z")
                    fill_timestamps(timestamps, previous_for_wallet[wallet]["fields"]["balance"], wallet)

            if coinmarketcap_file:
                with open(coinmarketcap_file, newline='') as f:
                    reader = csv.reader(f, delimiter=';', quoting=csv.QUOTE_NONE)
                    rows = []
                    for row in reader:
                        # Skip first line.
                        if row[3] != "close":
                            btc_price = float(row[3])
                            timestamp = row[6][1:-1]
                            #print("BTC price on %s: %f" % (timestamp, btc_price))
                            process_btc_price(price_usd=btc_price, timestamp_iso_format=timestamp, source="CoinMarketCap")

                    if len(influxdb_batch) > 0:
                        print("Batch with %d BTC prices left, publishing to InfluxDB." % len(influxdb_batch))
                        publish_to_influxdb(influxdb_batch)
                        influxdb_batch = []
                    else:
                        print("Batch empty, nothing left to publish to InfluxDB")

            if usd_chf_file:
                with open(usd_chf_file, newline='') as f:
                    reader = csv.reader(f, delimiter=',', quoting=csv.QUOTE_NONE)
                    rows = []
                    for row in reader:
                        rate = float(row[1])
                        # Format is like 06/16/2023
                        date = row[0]
                        date_split = date.split("/")
                        timestamp = "%s-%s-%sT00:00:00.000Z" % (date_split[2], date_split[0], date_split[1])
                        #print("BTC price on %s: %f" % (timestamp, btc_price))
                        process_usd_to_chf(exchange_rate=rate, timestamp_iso_format=timestamp)

                    if len(influxdb_batch) > 0:
                        print("Batch with %d exchange rates left, publishing to InfluxDB." % len(influxdb_batch))
                        publish_to_influxdb(influxdb_batch)
                        influxdb_batch = []
                    else:
                        print("Batch empty, nothing left to publish to InfluxDB")



# bitcoin2influxdb

Visualize your BTC balance evolution in Grafana.

Takes CSV files exported from Ledger Live or Electrum to import the Bitcoin transactions to InfluxDB.

Also import USD to CHF exchange rate and BTC price with CSV files.

## Prerequisites

* **Python 3**

Recommended: create a virtual env and install necessary dependencies:
```
python3 -m venv venv
. venv/bin/activate

pip install -r requirements.txt
```

* **InfluxDB and Grafana**

Start InfluxDB and Grafana with:
```
docker compose up -d
```

Username/password for both InfluxDB and Grafana is admin/123456789.

Access InfluxDB: http://localhost:8086
Access Grafana: http://localhost:3000

## Usage

```
usage: bitcoin2influxdb.py [-h] (-llf [LEDGER_LIVE_FILE] | -ef [ELECTRUM_FILE] | -cf [COINMARKETCAP_FILE] | -ucf [USD_CHF_FILE]) [-iu INFLUXDB_URL] [-it INFLUXDB_TOKEN] [-io INFLUXDB_ORG] [-ib INFLUXDB_BUCKET]
                           [-c [CACHE_FOLDER]]

Import Bitcoin transactions exported into InfluxDB.

optional arguments:
  -h, --help            show this help message and exit
  -llf [LEDGER_LIVE_FILE], --ledger_live_file [LEDGER_LIVE_FILE]
                        Path to Ledger Live CSV file
  -ef [ELECTRUM_FILE], --electrum_file [ELECTRUM_FILE]
                        Path to Electrum CSV file
  -cf [COINMARKETCAP_FILE], --coinmarketcap_file [COINMARKETCAP_FILE]
                        CoinMarketCap BTC price file
  -ucf [USD_CHF_FILE], --usd_chf_file [USD_CHF_FILE]
                        USD to CHF file
  -iu INFLUXDB_URL, --influxdb_url INFLUXDB_URL
                        InfluxDB URL, default: http://localhost:8086
  -it INFLUXDB_TOKEN, --influxdb_token INFLUXDB_TOKEN
                        InfluxDB token, default: my-super-secret-auth-token
  -io INFLUXDB_ORG, --influxdb_org INFLUXDB_ORG
                        InfluxDB org, default: my-org
  -ib INFLUXDB_BUCKET, --influxdb_bucket INFLUXDB_BUCKET
                        InfluxDB bucket, default: bitcoin
  -c [CACHE_FOLDER], --cache_folder [CACHE_FOLDER]
                        Folder where cache files are stored, default: cache
```


### Reset InfluxDB bucket

```
influx bucket delete --name bitcoin -c my-org
influx bucket create --name bitcoin --retention 0 -c my-org
```

## Cleanup

If you want to completely cleanup Docker volumes, run the following commands from the project root directory:

```
docker compose down

docker volume rm $(basename "$PWD")_grafana-storage
docker volume rm $(basename "$PWD")_influxdb-storage
```

## Resources

* [USD/CHF](https://www.investing.com/currencies/usd-chf-historical-data)

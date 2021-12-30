"""
Copilot injects the database credentials into the container runtime
environment via the FLAVORSCLUSTER_SECRET environment variable, which
contains JSON. Need to parse that and render out the settings.toml file at
runtime to get correct DB credentials into settings.toml file 
"""


import os
import sys
import time
import socket
import traceback
import argparse
import subprocess
import psycopg2
import toml
import json
from psycopg2.extras import execute_values

DB_CREDS_ENV_VAR = "FLAVORSCLUSTER_SECRET"
BLOCKCHAIN_NODE_SVC_NAME = "blockchain-node"
# Remember current direction is the WORKDIR in the docker file
# and this is relative to whatever WORKDIR is
BLOCKCHAIN_NODE_CONFIG_FILE_PATH = "./config/settings.toml"
BLOCKCHAIN_NODE_PROTOCOL = "http"
BLOCKCHAIN_NODE_PORT = 4467
ETL_LOG_DIR = "/opt/etl-lite"
ETL_BINARY_PATH = "./target/release/helium_etl_lite"

cli = argparse.ArgumentParser(description="""Helium ETL Lite AWS Copilot entrypoint""")
subparsers = cli.add_subparsers(dest="subcommand")


def subcommand(args=[], parent=subparsers):
    def decorator(func):
        parser = parent.add_parser(func.__name__, description=func.__doc__)
        for arg in args:
            parser.add_argument(*arg[0], **arg[1])
        parser.set_defaults(func=func)

    return decorator


def argument(*name_or_flags, **kwargs):
    return ([*name_or_flags], kwargs)


def get_service_info():
    db_creds = os.getenv(DB_CREDS_ENV_VAR)
    if db_creds is None:
        msg = "ERROR: DB creds environment variable {} is not set".format(
            DB_CREDS_ENV_VAR
        )
        print(msg)
        sys.exit(1)
    db_creds = json.loads(db_creds)
    service_endpoint = os.getenv("COPILOT_SERVICE_DISCOVERY_ENDPOINT", default="")
    db_url_str = "postgresql://{username}:{password}@{host}:{port}/{dbname}".format(
        **db_creds
    )
    print("db_url_str = {}".format(db_url_str))
    db_creds["url"] = db_url_str
    # This makes it work with both docker compose and copilot
    blockchain_node_hostname = (
        "{}.{}".format(BLOCKCHAIN_NODE_SVC_NAME, service_endpoint)
        if service_endpoint
        else BLOCKCHAIN_NODE_SVC_NAME
    )
    blockchain_node_addr = "{}://{}:{}".format(
        BLOCKCHAIN_NODE_PROTOCOL,
        blockchain_node_hostname,
        BLOCKCHAIN_NODE_PORT,
    )
    print("blockchain_node_addr = {}".format(blockchain_node_addr))
    svc_info = {"db": db_creds}
    svc_info[BLOCKCHAIN_NODE_SVC_NAME] = {
        "host": blockchain_node_hostname,
        "port": BLOCKCHAIN_NODE_PORT,
        "protocol": BLOCKCHAIN_NODE_PROTOCOL,
        "url": blockchain_node_addr,
    }
    return svc_info


def build_config_dict(svc_info, mode="full", backfill=True):
    """ """
    allowed_modes = {"full", "filters", "rewards"}
    if mode not in allowed_modes:
        msg = "Mode {} invalid, must be one of {}".format(mode, allowed_modes)
        raise ValueError(msg)
    config = {}
    config["database_url"] = svc_info["db"]["url"]
    config["node_addr"] = svc_info[BLOCKCHAIN_NODE_SVC_NAME]["url"]
    config["backfill"] = str(backfill).lower()
    config["mode"] = mode
    config["log"] = {"log_dir": ETL_LOG_DIR}
    return config


def write_config_dict_to_toml_file(path, config):
    with open(path, "w") as f:
        toml.dump(config, f)


def is_remote_port_open(host: str, port: int, timeout=2):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
    return result == 0


def check_remote_port_with_retry(
    host, port, retries=3, sleep_time=1, connection_timeout=1
):
    """ """
    for count in range(1, retries + 1):
        if is_remote_port_open(host, port, timeout=connection_timeout):
            print("Success: {}:{} is open".format(host, port))
            break
        print("Retry attempt {}, sleeping for {} seconds".format(count, sleep_time))
        time.sleep(sleep_time)
    else:
        msg = "Unable to connect to {}:{} after {} attempts".format(host, port, retries)
        raise RuntimeError(msg)


def write_filters_to_db(conf, svc_info):
    """
    Write accounts and gateway addresses to filters table of DB
    """
    mode = conf["mode"]
    accounts = os.getenv("ACCOUNT_ADDRESSES")
    gateways = os.getenv("GATEWAY_ADDRESSES")
    if mode == "filters" and not (accounts or gateways):
        print(
            "WARNING: Running in filters mode but neither ACCOUNT_ADDRESSES or GATEWAY_ADDRESSES env vars are set"
        )
        return False
    db_conn_keys = {
        "host": "host",
        "port": "port",
        "password": "password",
        "user": "username",
        "dbname": "dbname",
    }
    db_conn_dict = {k: svc_info["db"][v] for k, v in db_conn_keys.items()}
    if accounts:
        accounts_list = [["account", e] for e in accounts.split(",")]
        print("INFO: Writing accounts {} to filters table".format(accounts))
        with psycopg2.connect(**db_conn_dict) as conn:
            with conn.cursor() as curs:
                execute_values(
                    curs,
                    "INSERT INTO public.filters (type, value) VALUES %s",
                    accounts_list,
                )
    if gateways:
        gateways_list = [["gateway", e] for e in gateways.split(",")]
        print("INFO: Writing gateways {} to filters table".format(gateways))
        with psycopg2.connect(**db_conn_dict) as conn:
            with conn.cursor() as curs:
                execute_values(
                    curs,
                    "INSERT INTO public.filters (type, value) VALUES %s",
                    gateways_list,
                )
    print("INFO: Successfully wrote filters")
    return True


def run_with_returncode_passthru(args):
    """
    Run a subprocess and exit via sys.exit(proc.returncode) if the return code is
    non-zero
    """
    try:
        proc = subprocess.run(args, check=True)
    except subprocess.CalledProcessError as e:
        print(traceback.format_exc())
        sys.exit(e.returncode)


@subcommand(
    [
        argument(
            "-m",
            "--migrate",
            help="Run migrations before starting ETL",
            action="store_true",
        ),
        argument(
            "-b",
            "--backfill",
            help="Scan the node for the oldest block it has and start loading transactions from there.",
            action="store_true",
            default=True,
        ),
        argument(
            "-M",
            "--mode",
            help="Mode to run blockchain follder in",
            choices=["filters", "full", "rewards"],
            default="full",
        ),
    ]
)
def run(args):
    """
    Run the ETL service
    """
    svc_info = get_service_info()
    conf = build_config_dict(svc_info, mode=args.mode, backfill=args.backfill)
    write_config_dict_to_toml_file(BLOCKCHAIN_NODE_CONFIG_FILE_PATH, conf)
    for k in ("db", BLOCKCHAIN_NODE_SVC_NAME):
        check_remote_port_with_retry(
            svc_info[k]["host"], svc_info[k]["port"], retries=5, sleep_time=5
        )
    if args.migrate:
        run_with_returncode_passthru([ETL_BINARY_PATH, "migrate"])
    write_filters_to_db(conf, svc_info)
    run_with_returncode_passthru([ETL_BINARY_PATH, "start"])


@subcommand(
    [
        argument(
            "-b",
            "--backfill",
            help="Scan the node for the oldest block it has and start loading transactions from there.",
            action="store_true",
            default=True,
        ),
        argument(
            "-M",
            "--mode",
            help="Mode to run blockchain follder in",
            choices=["filters", "full", "rewards"],
            default="full",
        ),
    ]
)
def migrate(args):
    """
    Run database migrations for ETL service
    """
    svc_info = get_service_info()
    conf = build_config_dict(svc_info, mode=args.mode, backfill=args.backfill)
    write_config_dict_to_toml_file(BLOCKCHAIN_NODE_CONFIG_FILE_PATH, conf)
    for k in ("db", BLOCKCHAIN_NODE_SVC_NAME):
        check_remote_port_with_retry(
            svc_info[k]["host"], svc_info[k]["port"], retries=5, sleep_time=5
        )
    write_filters_to_db(conf, svc_info)
    run_with_returncode_passthru([ETL_BINARY_PATH, "migrate"])


@subcommand(
    [
        argument(
            "-b",
            "--backfill",
            help="Scan the node for the oldest block it has and start loading transactions from there.",
            action="store_true",
            default=True,
        ),
        argument(
            "-M",
            "--mode",
            help="Mode to run blockchain follder in",
            choices=["filters", "full", "rewards"],
            default="full",
        ),
    ]
)
def write_config(args):
    """
    Run database migrations for ETL service
    """
    svc_info = get_service_info()
    conf = build_config_dict(svc_info, mode=args.mode, backfill=args.backfill)
    write_config_dict_to_toml_file(BLOCKCHAIN_NODE_CONFIG_FILE_PATH, conf)


def main():
    args = cli.parse_args()
    if args.subcommand is None:
        cli.print_help()
    else:
        args.func(args)


if __name__ == "__main__":
    main()

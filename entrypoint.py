"""
Copilot injects the database credentials into the container runtime
environment via the FLAVORSCLUSTER_SECRET environment variable, which
contains JSON. Need to parse that and render out the settings.toml file at
runtime to get correct DB credentials into settings.toml file 
"""


import os
import sys
import traceback
import argparse
import subprocess
import toml
import json

DB_CREDS_ENV_VAR = "FLAVORSCLUSTER_SECRET"
BLOCKCHAIN_NODE_SVC_NAME = "blockchain-node"
# Remember current direction is the WORKDIR in the docker file
# and this is relative to whatever WORKDIR is 
BLOCKCHAIN_NODE_CONFIG_FILE_PATH = "./config/settings.toml"
ETL_LOG_DIR = "/opt/etl-lite"

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


def build_config_dict(mode="full", backfill=True):
    """
    """
    allowed_modes = {"full", "filters", "rewards"} 
    if mode not in allowed_modes:
        msg = "Mode {} invalid, must be one of {}".format(mode, allowed_modes)
        raise ValueError(msg)
    db_creds = os.getenv(DB_CREDS_ENV_VAR)
    if db_creds is None:
        msg = "ERROR: DB creds environment variable {} is not set".format(DB_CREDS_ENV_VAR)
        print(msg)
        sys.exit(1)
    db_creds = json.loads(db_creds)
    service_endpoint = os.getenv("COPILOT_SERVICE_DISCOVERY_ENDPOINT", default="")
    db_url_str = "postgressql://{username}:{password}@{host}:{port}/{dbname}".format(**db_creds)
    print("db_url_str = {}".format(db_url_str))
    # This makes it work with both docker compose and copilot
    blockchain_node_addr = "{}.{}".format(BLOCKCHAIN_NODE_SVC_NAME, service_endpoint) if service_endpoint else BLOCKCHAIN_NODE_SVC_NAME
    print("blockchain_node_addr = {}".format(blockchain_node_addr))
    config = {}
    config["database_url"] = db_url_str 
    config["node_addr"] = blockchain_node_addr 
    config["backfill"] = str(backfill).lower()
    config["mode"] = mode
    config['log'] = {'log_dir': ETL_LOG_DIR}
    return config

def write_config_dict_to_toml_file(path, config):
    with open(path, 'w') as f:
        toml.dump(config, f)

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
            help="If set, scan the node for the oldest block it has and start loading transactions from there.",
            action="store_true",
        ),
        argument(
            "-M",
            "--mode",
            help="Mode to run blockchain follder in",
            choices=["filters", "full", "rewards"],
            default="full"
        ),
    ]
)
def run(args):
    """ 
    """
    conf = build_config_dict(mode=args.mode, backfill=args.backfill)
    write_config_dict_to_toml_file(BLOCKCHAIN_NODE_CONFIG_FILE_PATH, conf)  
    if args.migrate:
        run_with_returncode_passthru(["./helium_etl_lite", "migrate"])
    run_with_returncode_passthru(["./helium_etl_lite", "start"])


def migrate(args):
    """ """
    run_with_returncode_passthru(["./helium_etl_lite", "migrate"])


def main():
    args = cli.parse_args()
    if args.subcommand is None:
        cli.print_help()
    else:
        args.func(args)


if __name__ == "__main__":
    main()

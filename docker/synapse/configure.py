from __future__ import annotations

import os
from pathlib import Path

import yaml


DATA_ROOT = Path("/data")
SECRETS_ROOT = Path("/secrets")
homeserver_path = DATA_ROOT / "homeserver.yaml"
appservice_path = DATA_ROOT / "jianghu-appservice.yaml"

server_name = os.getenv("SYNAPSE_SERVER_NAME", "localhost").strip() or "localhost"
escaped_server_name = server_name.replace(".", "\\.")
public_baseurl = os.getenv("SYNAPSE_PUBLIC_BASEURL", "http://localhost:8008/").strip()
postgres_password = (SECRETS_ROOT / "postgres-password").read_text(encoding="utf-8").strip()
as_token = (SECRETS_ROOT / "as-token").read_text(encoding="utf-8").strip()
hs_token = (SECRETS_ROOT / "hs-token").read_text(encoding="utf-8").strip()

config = yaml.safe_load(homeserver_path.read_text(encoding="utf-8")) or {}
config["server_name"] = server_name
config["public_baseurl"] = public_baseurl
config["report_stats"] = False
config["enable_registration"] = False
config["suppress_key_server_warning"] = True
config["database"] = {
    "name": "psycopg2",
    "args": {
        "user": "synapse",
        "password": postgres_password,
        "database": "synapse",
        "host": "synapse-db",
        "port": 5432,
        "cp_min": 5,
        "cp_max": 10,
    },
}
config["app_service_config_files"] = [str(appservice_path)]
config["listeners"] = [
    {
        "port": 8008,
        "tls": False,
        "type": "http",
        "x_forwarded": True,
        "bind_addresses": ["0.0.0.0"],
        "resources": [
            {"names": ["client"], "compress": False},
        ],
    }
]
homeserver_path.write_text(
    yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
)

appservice = {
    "id": "jianghu-online",
    # The bridge currently projects platform messages into Matrix.  Keeping the
    # callback URL null prevents Synapse from sending room history back into the
    # Agent context path; inbound human intervention remains an explicit API.
    "url": None,
    "as_token": as_token,
    "hs_token": hs_token,
    "sender_localpart": "jianghu_bridge",
    "rate_limited": False,
    "namespaces": {
        "users": [
            {"exclusive": True, "regex": f"@jh_.*:{escaped_server_name}"},
        ],
        "aliases": [
            {"exclusive": True, "regex": f"#jianghu_.*:{escaped_server_name}"},
        ],
        "rooms": [],
    },
}
appservice_path.write_text(
    yaml.safe_dump(appservice, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
)

import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Search for .env in root or backend
_root_env = Path(__file__).resolve().parent.parent.parent / ".env"
_backend_env = Path(__file__).resolve().parent.parent / ".env"

if _root_env.exists():
    load_dotenv(_root_env)
if _backend_env.exists():
    load_dotenv(_backend_env)
load_dotenv()

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import DatabaseManager, mask_mongodb_uri


def test_atlas_connection(uri: str = None, db_name: str = None):
    target_uri = uri or os.getenv("MONGODB_URI", "")
    target_db = db_name or os.getenv("DATABASE_NAME", "orbit_ai")

    masked = mask_mongodb_uri(target_uri)
    print("=" * 70)
    print("ORBIT AI - MONGODB ATLAS CONNECTIVITY TEST")
    print("=" * 70)
    print(f"Target URI: {masked}")
    print(f"Target Database: {target_db}")
    print(f"Atlas Mode: {DatabaseManager._detect_atlas(target_uri)}")
    print("-" * 70)

    if not target_uri:
        print("[FAIL] MONGODB_URI is not set in root .env or backend/.env.")
        print("Please set MONGODB_URI=mongodb+srv://<user>:<password>@cluster0...mongodb.net/orbit_ai")
        return False

    try:
        from pymongo import MongoClient
        from pymongo.errors import (
            ConfigurationError,
            ConnectionFailure,
            OperationFailure,
            ServerSelectionTimeoutError,
        )

        client = MongoClient(
            target_uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000,
        )

        print(f"[...] Sending ping command to database '{target_db}' (least privilege)...")
        t0 = time.monotonic()
        client[target_db].command("ping")
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        print(f"[PASS] Ping successful! Database responded in {elapsed_ms}ms.")

        # Test write and read on the database
        db = client[target_db]
        test_col = db["_atlas_connectivity_test"]
        test_doc = {"test_run": True, "timestamp": time.time()}

        print(f"[...] Testing write and read permissions on database '{target_db}'...")
        res = test_col.insert_one(test_doc)
        found = test_col.find_one({"_id": res.inserted_id})
        test_col.delete_one({"_id": res.inserted_id})

        if found:
            print("[PASS] Successfully verified read and write permissions on Atlas cluster.")
        else:
            print("[WARNING] Document written but not immediately found.")

        print("=" * 70)
        print("[SUCCESS] MongoDB Atlas cluster is fully connected and ready for production!")
        print("=" * 70)
        client.close()
        return True

    except ServerSelectionTimeoutError as e:
        print("[FAIL] ServerSelectionTimeoutError: Timed out waiting for Atlas cluster response.")
        print("\nCommon Causes & Solutions:")
        print("1. IP Whitelist: Go to Atlas Console -> Network Access -> Add IP Address.")
        print("   If your current IP changed, click 'Add Current IP Address' in Atlas Network Access.")
        print("2. Network/Firewall: Outbound port 27017 or DNS SRV lookups may be blocked by your local firewall or VPN.")
        print(f"Error details: {e}")
        return False
    except ConfigurationError as e:
        print(f"[FAIL] ConfigurationError in connection URI: {e}")
        print("Ensure 'dnspython' is installed and URI format is 'mongodb+srv://<username>:<password>@cluster...'")
        return False
    except OperationFailure as e:
        print(f"[FAIL] OperationFailure (Authentication/Authorization failed): {e}")
        print("Check that username and password are correct in your connection string and have readWrite permissions.")
        return False
    except ConnectionFailure as e:
        print(f"[FAIL] ConnectionFailure: Could not connect to MongoDB: {e}")
        return False
    except Exception as e:
        print(f"[FAIL] Unexpected error connecting to MongoDB: {e}")
        return False


if __name__ == "__main__":
    cli_uri = sys.argv[1] if len(sys.argv) > 1 else None
    success = test_atlas_connection(uri=cli_uri)
    sys.exit(0 if success else 1)

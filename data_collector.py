import re
import pandas as pd
import requests
import yaml

# --- Configuration ---

with open("config.yml", "r") as file:
    try:
        config = yaml.safe_load(file)
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file: {e}")

BASE_URL = config["api_url"]
EXCLUDED_INTERFACES = config["excluded_interfaces"]  # Exclude by exact interface name
EXCLUDED_DEVICES = config["excluded_devices"]  # Exclude by parsed Device name
EXCLUDED_INTERFACE_SUBSTRINGS = config["excluded_interface_substrings"]  # Exclude if interface name contains these strings


def parse_to_bps(value_str):
    if not value_str or pd.isna(value_str):
        return 0.0
    value_str = value_str.lower().strip()
    match = re.match(r"([\d.]+)\s*([a-z/]+)", value_str)
    if not match:
        return 0.0
    number, unit = float(match.group(1)), match.group(2)
    if "gb" in unit:
        return number * 1_000_000_000
    elif "mb" in unit:
        return number * 1_000_000
    elif "kb" in unit:
        return number * 1_000
    else:
        return number


def parse_port_speed_to_bps(speed_str):
    if not speed_str or speed_str == "Unknown":
        return 0.0
    speed_str = speed_str.lower().strip()
    match = re.match(r"([\d.]+)\s*([a-z]+)", speed_str)
    if not match:
        return 0.0
    number, unit = float(match.group(1)), match.group(2)
    if "g" in unit:
        return number * 1_000_000_000
    elif "m" in unit:
        return number * 1_000_000
    elif "k" in unit:
        return number * 1_000
    else:
        return number


def parse_title(title_str):
    try:
        parts = title_str.split(":")
        device = parts[0].strip()
        device_type = parts[1].strip()
        analysis_part = parts[2].split("Traffic Analysis for")[-1].strip()
        words = analysis_part.split()
        speed = words[-1] if words else "Unknown"
        org = " ".join(words[:-2]) if len(words) > 2 else analysis_part
        return device, device_type, org, speed
    except Exception:
        return "Unknown", "Unknown", "Unknown", "Unknown"


def fetch_mrtg_data():
    try:
        response = requests.get(BASE_URL)
        response.raise_for_status()
        interfaces_map = response.json()
    except Exception as e:
        print(f"Error connecting to base URL: {e}")
        return pd.DataFrame()

    all_records = []

    for int_name, render_url in interfaces_map.items():
        # 1. Filter by specific Interface Name (Exact Match)
        if int_name in EXCLUDED_INTERFACES:
            print(f"Skipping excluded interface (exact match): {int_name}")
            continue

        # 2. Filter by Interface Name Substring (Partial Match)
        if any(substring in int_name for substring in EXCLUDED_INTERFACE_SUBSTRINGS):
            print(f"Skipping excluded interface (substring match): {int_name}")
            continue

        raw_url = render_url.replace("/render", "").replace("https:// ", "http://")

        try:
            data_resp = requests.get(raw_url)
            data_resp.raise_for_status()
            raw_data = data_resp.json()

            device, device_type, org, speed = parse_title(raw_data.get("title", ""))

            # 3. Filter by specific Device Name
            if device in EXCLUDED_DEVICES:
                print(f"Skipping excluded device: {device} (Interface: {int_name})")
                continue

            port_capacity_bps = parse_port_speed_to_bps(speed)

            for duration in ["day", "week", "month", "year"]:
                duration_data = raw_data.get(duration, {})

                # Extract Raw Max and Average values
                in_max_raw = duration_data.get("in", {}).get("max", "0 b/s")
                out_max_raw = duration_data.get("out", {}).get("max", "0 b/s")
                in_avg_raw = duration_data.get("in", {}).get("average", "0 b/s")
                out_avg_raw = duration_data.get("out", {}).get("average", "0 b/s")

                # Parse to bps
                in_max_bps = parse_to_bps(in_max_raw)
                out_max_bps = parse_to_bps(out_max_raw)
                in_avg_bps = parse_to_bps(in_avg_raw)
                out_avg_bps = parse_to_bps(out_avg_raw)

                # Calculate Percentages
                in_max_pct = (in_max_bps / port_capacity_bps * 100) if port_capacity_bps > 0 else 0.0
                out_max_pct = (out_max_bps / port_capacity_bps * 100) if port_capacity_bps > 0 else 0.0
                in_avg_pct = (in_avg_bps / port_capacity_bps * 100) if port_capacity_bps > 0 else 0.0
                out_avg_pct = (out_avg_bps / port_capacity_bps * 100) if port_capacity_bps > 0 else 0.0

                all_records.append({
                    "Interface": int_name,
                    "Device": device,
                    "Type": device_type,
                    "Org": org,
                    "Port Speed": speed,
                    "Duration": duration,
                    "In Max (Raw)": in_max_raw,
                    "Out Max (Raw)": out_max_raw,
                    "In Avg (Raw)": in_avg_raw,
                    "Out Avg (Raw)": out_avg_raw,
                    "In Max Utilisation (%)": round(in_max_pct, 2),
                    "Out Max Utilisation (%)": round(out_max_pct, 2),
                    "In Avg Utilisation (%)": round(in_avg_pct, 2),
                    "Out Avg Utilisation (%)": round(out_avg_pct, 2),
                })

        except Exception as e:
            print(f"Failed to process data from {raw_url}: {e}")

    return pd.DataFrame(all_records)


if __name__ == "__main__":
    df = fetch_mrtg_data()
    df.to_csv("mrtg_data.csv", index=False)

import os
import requests
import json
import base64
from datetime import datetime
import time
from bs4 import BeautifulSoup
import math
import matplotlib.pyplot as plt
import re
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://www.recurse.com/api/v1"
TOKEN = os.getenv("RECURSE_TOKEN")

ZULIP_BASE_URL = "https://recurse.zulipchat.com/api/v1"
ZULIP_EMAIL = os.getenv("ZULIP_EMAIL")
ZULIP_KEY = os.getenv("ZULIP_KEY")
ZULIP_AUTH_CODE = base64.b64encode(f"{ZULIP_EMAIL}:{ZULIP_KEY}".encode()).decode()

def rc_api_request(endpoint: str):
    response = requests.get(f"{BASE_URL}/{endpoint}", headers={
        "Authorization": f"Bearer {TOKEN}"
    })
    return response.json()

def zulip_api_request(endpoint: str, params: dict):
    response = requests.get(f"{ZULIP_BASE_URL}/{endpoint}", params=params, headers={
        "Authorization": f"Basic {ZULIP_AUTH_CODE}"
    })
    return response.json()

def download_profiles():
    print("Downloading profiles...")
    all_profiles = []
    offset = 0
    while True:
        next_profiles = rc_api_request(f"profiles?offset={offset}&limit=50")
        print(next_profiles)
        all_profiles.extend(next_profiles)
        if len(next_profiles) < 50:
            break
        offset += len(next_profiles)
    with open("profiles.json", mode="w") as f:
        json.dump(all_profiles, f)

def load_profiles() -> list:
    if not os.path.exists("profiles.json"):
        download_profiles()
    with open("profiles.json", "r") as f:
        return json.load(f)

def download_batches():
    print("Downloading batches...")
    checkins = load_converted_checkins()
    checkins_start_time = checkins[0]["timestamp"]
    batches = rc_api_request("batches")
    result = []
    for batch in batches:
        name = batch["name"]
        if "Mini" not in name:
            start_time = datetime.strptime(batch["start_date"], "%Y-%m-%d").timestamp()
            end_time = datetime.strptime(batch["end_date"], "%Y-%m-%d").timestamp()
            if end_time > checkins_start_time:
                result.append({
                    "name": name,
                    "start": start_time,
                    "end": end_time
                })
    result.sort(key=lambda b: b["start"])
    with open("batches.json", mode="w") as f:
        json.dump(result, f)

def load_batches() -> list:
    if not os.path.exists("batches.json"):
        download_batches()
    with open("batches.json", "r") as f:
        return json.load(f)

def create_zulip_to_rc_map() -> dict[int, int]:
    result = {}
    profiles = load_profiles()
    for profile in profiles:
        if profile["zulip_id"] is not None:
            result[profile["zulip_id"]] = profile["id"]
    return result

def download_checkins():
    print("Downloading checkins...")
    all_messages = []
    anchor = "newest"
    block_size = 1000
    while True:
        response = zulip_api_request("messages", {
            "anchor": anchor,
            "num_before": block_size,
            "num_after": 0,
            "narrow": json.dumps([
                {"operator": "channel", "operand": "checkins"}
            ])
        })
        messages = response["messages"]
        if anchor != "newest":
            messages = messages[:-1]
        if len(messages) > 0:
            print(f"{messages[0]["id"]} .. {messages[-1]["id"]} ({len(messages)} total)")
        else:
            break
        all_messages.extend(messages)
        anchor = messages[0]["id"]
        time.sleep(0.5)
    with open("checkins.json", "w") as f:
        json.dump(all_messages, f)

def load_checkins() -> list:
    if not os.path.exists("checkins.json"):
        download_checkins()
    with open("checkins.json", "r") as f:
        return json.load(f)

def convert_checkins():
    print("Converting checkins...")
    checkins = load_checkins()
    zulip_to_rc_map = create_zulip_to_rc_map()
    result = []
    for message in checkins:
        sender_id = message["sender_id"]
        if sender_id in zulip_to_rc_map:
            timestamp = message["timestamp"]
            rc_id = zulip_to_rc_map[sender_id]
            soup = BeautifulSoup(message["content"])
            result.append({ "sender": rc_id, "timestamp": timestamp, "content": soup.text })
    result.sort(key=lambda m: m["timestamp"])
    with open("converted_checkins.json", "w") as f:
        json.dump(result, f)

def load_converted_checkins() -> list:
    if not os.path.exists("converted_checkins.json"):
        convert_checkins()
    with open("converted_checkins.json", "r") as f:
        return json.load(f)

batches = load_batches()
checkins = load_converted_checkins()
start_time = batches[0]["start"]
end_time = checkins[-1]["timestamp"]

week = 60 * 60 * 24 * 7
batch_week_table = []
b = 0
t = start_time
while t < end_time:
    if b + 1 < len(batches) and t > batches[b + 1]["start"]:
        b += 1
    batch_week_table.append(b)
    t += week

dates = [datetime.fromtimestamp(b["start"]) for b in batches]

def get_batch_number(timestamp: int) -> int:
    return batch_week_table[math.floor((timestamp - start_time) / week)]

def get_interest_data(keywords: list[str]) -> list[float]:
    lower_keywords = [keyword.lower() for keyword in keywords]
    delimiter_regex = "\\ |\\.|\\?|!|,|\\\\|\\/|\\&|\\*"
    regex = "|".join(f"(({delimiter_regex}|^){k}({delimiter_regex}|$))" for k in lower_keywords)
    pattern = re.compile(regex)

    bins = [0 for _ in batches]
    bin_totals = [0 for _ in batches]
    for message in checkins:
        batch_number = get_batch_number(message["timestamp"])
        bin_totals[batch_number] += 1
        if re.search(pattern, message["content"].lower()):
            bins[batch_number] += 1

    for i in range(len(bins)):
        bins[i] /= max(bin_totals[i], 100)

    return bins

def plot_interest(plot_name: str, title: str | None, lines: list[list[str]]):
    print(f"Plotting {plot_name}...")
    fig, ax = plt.subplots()
    ax.set_xlabel("Time")
    ax.set_ylabel("Mention Frequency")
    for line in lines:
        ax.plot(dates, get_interest_data(line))
    ax.legend(["/".join(keywords) for keywords in lines])
    if title:
        ax.set_title(title)
    fig.savefig(plot_name, dpi=400)
    plt.close(fig)

def get_total_checkin_counts() -> list[float]:
    bin_totals = [0 for _ in batches]
    for message in checkins:
        batch_number = get_batch_number(message["timestamp"])
        bin_totals[batch_number] += 1
    return bin_totals

def plot_total_checkin_counts(plot_name: str, title: str | None):
    print(f"Plotting {plot_name}...")
    fig, ax = plt.subplots()
    ax.set_xlabel("Time")
    ax.set_ylabel("Messages")
    ax.plot(dates, get_total_checkin_counts())
    ax.legend(["Total Checkin Messages"])
    if title:
        ax.set_title(title)
    fig.savefig(plot_name, dpi=400)
    plt.close(fig)

plot_interest("llms.png", None, [
    ["LLM", "LLMs"]
])

plot_interest("llms_vs_vibecoding.png", None, [
    ["LLM", "LLMs"],
    ["Vibecoding", "Vibe coding"]
])

plot_interest("vim_vs_emacs.png", None, [
    ["Vim"],
    ["Emacs"]
])

plot_interest("vim_emacs_vs_vscode.png", None, [
    ["Vim", "Emacs"],
    ["Vscode", "VS Code"]
])

plot_interest("apples_vs_oranges.png", "Apples vs. Oranges", [
    ["Apple"],
    ["Orange"]
])

plot_interest("pairing.png", None, [
    ["pairing", "paired"],
])

plot_interest("pairing_vs_covid.png", None, [
    ["Pairing", "Paired"],
    ["Covid", "Coronavirus"]
])

plot_interest("pairing_vs_hub.png", None, [
    ["Pairing", "Paired"],
    ["Hub"]
])

plot_interest("remote_vs_hub.png", None, [
    ["Remote"],
    ["Hub"]
])

plot_interest("ai_vs_ml.png", None, [
    ["AI"],
    ["Machine learning", "ML"]
])

plot_interest("rcade.png", None, [
    ["rcade"],
])

plot_interest("smalltalk_elixir.png", None, [
    ["Smalltalk"],
    ["Elixir", "Erlang"]
])

plot_interest("covid.png", None, [
    ["Covid", "Coronavirus"]
])

plot_interest("hub.png", None, [
    ["Hub"]
])

plot_interest("covid_vs_hub.png", None, [
    ["Hub"],
    ["Covid", "Coronavirus"]
])

plot_interest("ai_vs_llms.png", None, [
    ["AI"],
    ["LLM", "LLMs"]
])

plot_interest("apples_vs_oranges.png", None, [
    ["Apple", "Apples"],
    ["Orange", "Oranges"]
])

plot_interest("rust.png", None, [
    ["Rust"],
])

plot_interest("gpu.png", None, [
    ["GPU", "GPUs"],
])

plot_interest("javascript_vs_typescript.png", None, [
    ["Javascript", "JS"],
    ["Typescript", "Type script"]
])

plot_total_checkin_counts("total_checkins.png", None)
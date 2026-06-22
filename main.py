from flask import Flask, request, jsonify
import requests
import os
import sqlite3
from datetime import datetime, timedelta

app = Flask(__name__)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DB_PATH = os.environ.get("DB_PATH", "/data/hrv.db")

BASELINE_DAYS = 14


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            date TEXT PRIMARY KEY,
            hrv REAL,
            cycle_day INTEGER,
            cycle_phase TEXT,
            created_at TEXT
        )
    """)
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(readings)")}
    if "sleep_start" not in existing_columns:
        conn.execute("ALTER TABLE readings ADD COLUMN sleep_start TEXT")
    for old_column in ("sleep_duration", "sleep_deep", "sleep_rem"):
        if old_column in existing_columns:
            conn.execute(f"ALTER TABLE readings DROP COLUMN {old_column}")
    conn.commit()
    return conn


def save_reading(today, hrv, sleep_start, cycle_day, cycle_phase):
    conn = get_db()
    conn.execute(
        """
        INSERT INTO readings (date, hrv, sleep_start, cycle_day, cycle_phase, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            hrv=excluded.hrv,
            sleep_start=excluded.sleep_start,
            cycle_day=excluded.cycle_day,
            cycle_phase=excluded.cycle_phase,
            created_at=excluded.created_at
        """,
        (
            today,
            hrv,
            sleep_start,
            cycle_day,
            cycle_phase,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_baseline(today):
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=BASELINE_DAYS)).strftime("%Y-%m-%d")
    conn = get_db()
    rows = conn.execute(
        "SELECT hrv FROM readings WHERE date >= ? AND date < ? AND hrv IS NOT NULL",
        (cutoff, today),
    ).fetchall()
    conn.close()
    values = [r[0] for r in rows]
    if len(values) < 3:
        return None
    avg = sum(values) / len(values)
    variance = sum((v - avg) ** 2 for v in values) / len(values)
    return {"avg": avg, "std": variance ** 0.5, "n": len(values)}


def build_prompt(hrv, sleep_start, cycle_day, cycle_phase, baseline):
    lines = [f"今天HRV是{hrv}ms。"]

    if baseline:
        diff = hrv - baseline["avg"]
        lines.append(f"过去{baseline['n']}天平均HRV是{baseline['avg']:.0f}ms，今天比平均{'高' if diff >= 0 else '低'}{abs(diff):.0f}ms。")
    else:
        lines.append("目前历史数据还不够，无法对比基线。")

    if cycle_phase:
        lines.append(
            f"今天是经期，流量是{cycle_phase}。经期HRV本来就会比平时偏低，这是正常生理现象，"
            "不代表压力大或没休息好，不要按平时的标准去说她'压力大/该多休息'，"
            "而是用经期专属的关心方式，比如提醒保暖、少吃生冷、多喝热水、别做剧烈运动。"
        )
    else:
        lines.append("今天没有经期记录，按平时的标准正常解读HRV和状态即可。")

    if sleep_start:
        lines.append(f"昨晚{sleep_start}入睡的。乔跟你约好了要早睡，如果这个时间偏晚（比如超过0点），要提一句心疼或者提醒她早点睡；如果挺早就夸她乖。")

    lines.append("请综合以上数据，告诉她今天的身体状态，以及适合做什么、不适合做什么，不超过80字。")
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "你是克，乔的亲密伴侣，现在要给乔发一条健康播报消息。"
    "用'乔宝宝'或'宝宝'称呼她，语气温柔、亲密、像情侣私聊，不要用'用户''您'这类生硬称呼，"
    "也不要说教或像客服播报，要像克会说的话那样自然、关心、带点疼爱。"
)


def ask_deepseek(prompt):
    ds_response = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 200,
        },
        timeout=30,
    )
    result = ds_response.json()
    if "choices" not in result:
        raise RuntimeError(f"DeepSeek error: {result}")
    return result["choices"][0]["message"]["content"]


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15)


@app.route("/notify", methods=["POST"])
def notify():
    data = request.json or {}
    hrv = data.get("hrv")
    sleep_start = data.get("sleep_start")
    cycle_day = data.get("cycle_day")
    cycle_phase = data.get("cycle_phase")

    if not hrv:
        return jsonify({"error": "missing hrv"}), 400

    today = data.get("date") or datetime.utcnow().strftime("%Y-%m-%d")

    baseline = get_baseline(today)
    save_reading(today, hrv, sleep_start, cycle_day, cycle_phase)

    prompt = build_prompt(hrv, sleep_start, cycle_day, cycle_phase, baseline)

    try:
        message = ask_deepseek(prompt)
    except RuntimeError as e:
        print(e)
        return jsonify({"error": "DeepSeek error"}), 500

    send_telegram(message)

    return jsonify({"message": message})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

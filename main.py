from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
BARK_URL = os.environ.get("BARK_URL")  # 格式: https://api.day.app/你的key

@app.route("/notify", methods=["POST"])
def notify():
    data = request.json
    hrv = data.get("hrv")
    
    if not hrv:
        return jsonify({"error": "missing hrv"}), 400

    # 调DeepSeek
    ds_response = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "deepseek-chat",
            "messages": [{
                "role": "user",
                "content": f"我的HRV值是{hrv}ms，请用一句温柔的中文告诉我现在的身体状态，像朋友一样，不超过30字。"
            }],
            "max_tokens": 100
        }
    )
    
    message = ds_response.json()["choices"][0]["message"]["content"]
    
    # 发Bark
    requests.get(f"{BARK_URL}/{message}")
    
    return jsonify({"message": message})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

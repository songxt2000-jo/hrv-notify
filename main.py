from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
BARK_URL = os.environ.get("BARK_URL")

@app.route("/notify", methods=["POST"])
def notify():
    data = request.json
    hrv = data.get("hrv")
    
    if not hrv:
        return jsonify({"error": "missing hrv"}), 400

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
    
    result = ds_response.json()
    print("DeepSeek response:", result)
    
    if "choices" not in result:
        return jsonify({"error": "DeepSeek error", "detail": result}), 500
    
    message = result["choices"][0]["message"]["content"]
    
    bark_url = BARK_URL.rstrip("/")
    requests.get(f"{bark_url}/{message}")
    
    return jsonify({"message": message})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

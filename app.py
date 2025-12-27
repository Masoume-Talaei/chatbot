from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import os
from openai import OpenAI
import base64
import re  

load_dotenv()

api_key = os.getenv("AIMLAPI_KEY")
if not api_key:
    raise RuntimeError("لطفاً AIMLAPI_KEY را در فایل .env تنظیم کنید!")

client = OpenAI(
    api_key=api_key,
    base_url="https://api.aimlapi.com/v1"
)

app = Flask(__name__, static_folder="static", template_folder="templates")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.form.get("message", "").strip()
    file = request.files.get("file")

    messages = [
        {
            "role": "system",
            "content": "تو یک دستیار هوشمند و دوستانه به زبان فارسی هستی. همیشه به فارسی روان و طبیعی پاسخ بده. اگر عکس دریافت کردی، محتوای آن را با دقت توصیف کن، تحلیل بده یا به سؤال کاربر درباره آن پاسخ بده."
        }
    ]

    user_content = []

    if user_message:
        user_content.append({"type": "text", "text": user_message})

    if file and file.filename != '':
        if file.mimetype.startswith('image/'):
            try:
                file_bytes = file.read()
                if len(file_bytes) > 10 * 1024 * 1024:  # 10MB
                    return jsonify({"reply": "عکس خیلی بزرگه! حداکثر ۱۰ مگابایت مجاز هست."})

                base64_image = base64.b64encode(file_bytes).decode('utf-8')
                image_data_url = f"data:{file.mimetype};base64,{base64_image}"

                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": image_data_url}
                })

            except Exception as e:
                print("خطا در پردازش عکس:", e)
                return jsonify({"reply": "مشکلی در پردازش عکس پیش اومد. لطفاً دوباره امتحان کن."})
        else:
            return jsonify({"reply": "فعلاً فقط از عکس پشتیبانی می‌کنم 😅\nفایل‌های PDF و متن بعداً اضافه می‌شن!"})

    if not user_content:
        return jsonify({"error": "پیام یا عکسی ارسال نشده"}), 400

    messages.append({"role": "user", "content": user_content})

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )

        bot_reply_raw = response.choices[0].message.content

        bot_reply = bot_reply_raw

        bot_reply = re.sub(r'\*\*(.*?)\*\*', r'\1', bot_reply)
        bot_reply = re.sub(r'__(.*?)__', r'\1', bot_reply)
        bot_reply = re.sub(r'\*(.*?)\*', r'\1', bot_reply)
        bot_reply = re.sub(r'_(.*?)_', r'\1', bot_reply)

        bot_reply = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', bot_reply)

        bot_reply = re.sub(r'```[\s\S]*?```', '', bot_reply)
        bot_reply = re.sub(r'`(.*?)`', r'\1', bot_reply)

        bot_reply = re.sub(r'^#+\s*', '', bot_reply, flags=re.MULTILINE)

        bot_reply = re.sub(r'^\s*[-*•]\s+', '', bot_reply, flags=re.MULTILINE)
        bot_reply = re.sub(r'^\s*\d+\.\s+', '', bot_reply, flags=re.MULTILINE)

        bot_reply = re.sub(r'\n\s*\n\s*\n', '\n\n', bot_reply)
        bot_reply = bot_reply.strip()

        # ================================================

        return jsonify({"reply": bot_reply})

    except Exception as e:
        print("خطای کامل:", e)

        if hasattr(e, 'response') and e.response is not None:
            try:
                error_body = e.response.json()
                error_msg = error_body.get('error', {}).get('message', '').lower()

                if any(k in error_msg for k in ["credit", "quota", "insufficient", "rate limit", "forbidden"]):
                    return jsonify({"reply": "متأسفانه محدودیت استفاده ساعتی یا اعتباری من پر شده 😅\nلطفاً یک ساعت دیگه دوباره امتحان کن، تا اون موقع دوباره شارژ می‌شم! ⏳"})
            except:
                pass

        return jsonify({"reply": "خطایی در ارتباط با سرور پیش اومد. لطفاً دوباره امتحان کن."}), 500

if __name__ == "__main__":
    app.run(debug=True)  
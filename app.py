from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import os
from openai import OpenAI
import base64
import re
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    raise RuntimeError("لطفاً OPENROUTER_API_KEY را در فایل .env تنظیم کنید!")

client = OpenAI(
    api_key=api_key,
    base_url="https://openrouter.ai/api/v1"
)

app = Flask(__name__, static_folder="static", template_folder="templates")

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat_history.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(10), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image_base64 = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat_list")
def get_chat_list():
    subquery = db.session.query(
        Message.session_id,
        db.func.max(Message.timestamp).label('max_timestamp')
    ).group_by(Message.session_id).subquery()

    latest_messages = db.session.query(Message).join(
        subquery,
        (Message.session_id == subquery.c.session_id) &
        (Message.timestamp == subquery.c.max_timestamp)
    ).order_by(Message.timestamp.desc()).all()

    chat_list = []
    for msg in latest_messages:
        title = msg.content.strip()
        if not title or title == "[عکس ارسال شده]":
            title = "مکالمه جدید"
        elif len(title) > 40:
            title = title[:40] + "..."

        chat_list.append({
            "id": msg.session_id,
            "title": title
        })

    return jsonify(chat_list)

@app.route("/history")
def get_history():
    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify([])

    messages = Message.query.filter_by(session_id=session_id).order_by(Message.timestamp.asc()).all()
    history = []
    for msg in messages:
        item = {"role": msg.role, "content": msg.content}
        if msg.image_base64:
            item["image"] = f"data:image/jpeg;base64,{msg.image_base64}"
        history.append(item)
    return jsonify(history)

@app.route("/chat", methods=["POST"])
def chat():
    session_id = request.headers.get('X-Session-ID')
    if not session_id:
        return jsonify({"error": "session_id لازم است"}), 400

    user_message = request.form.get("message", "").strip()
    file = request.files.get("file")

    user_content = []
    image_base64 = None

    if user_message:
        user_content.append({"type": "text", "text": user_message})

    if file and file.filename != '':
        if file.mimetype.startswith('image/'):
            try:
                file_bytes = file.read()
                if len(file_bytes) > 10 * 1024 * 1024:
                    return jsonify({"reply": "عکس خیلی بزرگه! حداکثر ۱۰ مگابایت."})

                base64_image = base64.b64encode(file_bytes).decode('utf-8')
                image_data_url = f"data:{file.mimetype};base64,{base64_image}"
                image_base64 = base64_image

                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": image_data_url}
                })
            except Exception as e:
                print("خطا در عکس:", e)
                return jsonify({"reply": "مشکلی در پردازش عکس پیش اومد."})
        else:
            return jsonify({"reply": "فعلاً فقط عکس قبول می‌کنم 😅"})

    if not user_content:
        return jsonify({"error": "پیام یا عکسی ارسال نشده"}), 400

    
    db.session.add(Message(
        session_id=session_id,
        role="user",
        content=user_message or "[عکس ارسال شده]",
        image_base64=image_base64
    ))
    db.session.commit()

    history = Message.query.filter_by(session_id=session_id).order_by(Message.timestamp).limit(30).all()

    messages = [{"role": "system", "content": "تو یک دستیار هوشمند و دوستانه به زبان فارسی هستی. همیشه به فارسی روان و طبیعی پاسخ بده."}]

    for msg in history:
        if msg.role == "user":
            content = []
            if msg.content != "[عکس ارسال شده]":
                content.append({"type": "text", "text": msg.content})
            if msg.image_base64:
                content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{msg.image_base64}"}})
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "assistant", "content": msg.content})

    messages.append({"role": "user", "content": user_content})

    try:
        response = client.chat.completions.create(
            model="qwen/qwen-2.5-vl-7b-instruct:free",
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

        db.session.add(Message(session_id=session_id, role="bot", content=bot_reply))
        db.session.commit()

        return jsonify({"reply": bot_reply})

    except Exception as e:
        print("خطا:", e)
        return jsonify({"reply": "یه مشکلی پیش اومد، چند لحظه دیگه امتحان کن 😅"})

if __name__ == "__main__":
    app.run(debug=True)
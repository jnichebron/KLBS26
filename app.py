from flask import Flask, render_template, request, redirect, session, send_file
import sqlite3
import os
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
import base64
import time
import numpy as np
import cv2
from openpyxl import Workbook
import logging
import threading

app = Flask(__name__)
app.secret_key = "klbs_admin_secret_2026"

logging.basicConfig(level=logging.INFO)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")

UPLOAD_FOLDER = os.path.join(BASE_DIR, "static/uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "klbsTG2026"

SESSION_TIMEOUT = 1800


# ================= SESSION GUARD =================
@app.before_request
def session_guard():
    protected = ["/admin", "/delete", "/checkin", "/export-excel", "/admin-mobile"]

    if any(request.path.startswith(p) for p in protected):
        if not session.get("admin"):
            return redirect("/login")

        last = session.get("last_active")
        if last and time.time() - last > SESSION_TIMEOUT:
            session.clear()
            return redirect("/login")

        session["last_active"] = time.time()


# ================= USERS COUNT =================
def get_total_users():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    conn.close()
    return total


# ================= FACE VALIDATION =================
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

def validate_face(image_base64):
    try:
        if not image_base64 or "," not in image_base64:
            return False, "Invalid image"

        img_data = base64.b64decode(image_base64.split(",")[1])
        np_arr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if img is None:
            return False, "Image error"

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        faces = face_cascade.detectMultiScale(gray, 1.1, 8, minSize=(100, 100))

        if len(faces) == 0:
            return False, "No face detected"

        if len(faces) > 1:
            return False, "Only one face allowed"

        if cv2.Laplacian(gray, cv2.CV_64F).var() < 80:
            return False, "Image too blurry"

        if np.mean(gray) < 70:
            return False, "Image too dark"

        return True, "OK"

    except Exception as e:
        logging.error(e)
        return False, "Face validation failed"


# ================= SAVE IMAGE =================
def save_image(base64_img):
    img_data = base64.b64decode(base64_img.split(",")[1])
    filename = f"{int(time.time())}.jpg"
    path = os.path.join(UPLOAD_FOLDER, filename)

    with open(path, "wb") as f:
        f.write(img_data)

    return f"uploads/{filename}"


# ================= TAG SYSTEM =================
def generate_next_tag():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT tag FROM users")
    rows = cur.fetchall()
    conn.close()

    used = set()

    for r in rows:
        if r[0] and r[0].startswith("TG-"):
            try:
                used.add(int(r[0].split("-")[1]))
            except:
                pass

    i = 1
    while i in used:
        i += 1

    return f"TG-{i:03d}"


# ================= EMAIL (FIXED FOR RENDER) =================
def send_email(to_email, name, tag):
    sender_email = os.getenv("EMAIL_USER", "jnichebron@gmail.com")
    sender_password = os.getenv("EMAIL_PASS", "rtcn yfup cjau ryrr")

    try:
        body = f"""Hello {name},

Your KLBS26 registration has been successfully received.

Your Tag: {tag}

Date: 18–19 July 2026
Time: 8:00 AM
Venue: 130 Aka Itiam Street, Uyo, Akwa Ibom State
"""

        msg = MIMEText(body)
        msg["Subject"] = "KLBS26 Registration"
        msg["From"] = sender_email
        msg["To"] = to_email

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.set_debuglevel(1)  # IMPORTANT: shows real errors in logs
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()

        logging.info("EMAIL SENT SUCCESSFULLY")

    except Exception as e:
        logging.error(f"EMAIL FAILED: {e}")


# ================= ROUTES =================
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["POST"])
def register():

    if get_total_users() >= 100:
        return render_template("index.html", error="Registration closed")

    name = request.form.get("full_name")
    phone = request.form.get("phone")
    email = request.form.get("email")
    image = request.form.get("captured_image")

    valid, msg = validate_face(image)
    if not valid:
        return render_template("index.html", error=msg)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE phone=? OR email=?", (phone, email))
    if cur.fetchone():
        return render_template("index.html", error="Already registered")

    image_path = save_image(image)
    tag = generate_next_tag()

    cur.execute("""
        INSERT INTO users (
            full_name, phone, email,
            occupation, location,
            expectations, goals,
            referral, referral_other,
            tag, image, checked_in, created_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?)
    """, (
        name,
        phone,
        email,
        request.form.get("occupation"),
        request.form.get("location"),
        request.form.get("expectations"),
        request.form.get("goals"),
        request.form.get("referral"),
        request.form.get("referral_other"),
        tag,
        image_path,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    conn.commit()
    conn.close()

    # 🔥 TEMP FIX: NO THREADING (IMPORTANT FOR DEBUGGING)
    send_email(email, name, tag)

    return render_template("success.html", name=name, tag=tag)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == ADMIN_USERNAME and request.form["password"] == ADMIN_PASSWORD:
            session["admin"] = True
            session["last_active"] = time.time()
            return redirect("/admin")

        return render_template("login.html", error="Invalid login")

    return render_template("login.html")


@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect("/login")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM users ORDER BY id DESC")
    users = cur.fetchall()

    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]

    conn.close()

    return render_template("admin.html", users=users, total=total)


@app.route("/admin-mobile")
def admin_mobile():
    if not session.get("admin"):
        return redirect("/login")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM users ORDER BY id DESC")
    users = cur.fetchall()

    conn.close()

    return render_template("admin_mobile.html", users=users)


@app.route("/checkin/<int:user_id>")
def checkin(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET checked_in=1 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return redirect("/admin")


@app.route("/delete/<int:user_id>")
def delete(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return redirect("/admin")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/export-excel")
def export_excel():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT full_name, phone, email, occupation, location, expectations, goals, referral, referral_other, tag, checked_in, created_at FROM users")
    rows = cur.fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.append(["Name","Phone","Email","Occupation","Location","Expectations","Goals","Referral","Other","Tag","Checked","Date"])

    for r in rows:
        ws.append(list(r))

    file_path = os.path.join(BASE_DIR, "export.xlsx")
    wb.save(file_path)

    return send_file(file_path, as_attachment=True)


# ================= RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

from flask import Flask, render_template, request, redirect, url_for
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
from collections import defaultdict
from flask_bcrypt import Bcrypt
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from itsdangerous import URLSafeTimedSerializer
import matplotlib.pyplot as plt
import io
import base64
import os
from werkzeug.utils import secure_filename

# === Flask App Config ===
app = Flask(__name__)
app.secret_key = "super-secret"

# === MongoDB Setup ===
client = MongoClient("mongodb://localhost:27017/")
db = client["expense_tracker"]
expenses_collection = db["expenses"]
users_collection = db["users"]

# === Upload Folder ===
UPLOAD_FOLDER = "static/profile_pics"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# === Flask Extensions ===
bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)
s = URLSafeTimedSerializer("secret-key")


# === User Model ===
class User(UserMixin):
    def __init__(self, user_doc):
        self.id = str(user_doc["_id"])
        self.email = user_doc["email"]
        self.name = user_doc.get("name", "")
        self.profile_pic = user_doc.get("profile_pic", "default.png")


@login_manager.user_loader
def load_user(user_id):
    user_doc = users_collection.find_one({"_id": ObjectId(user_id)})
    return User(user_doc) if user_doc else None


# === Routes ===
@app.route("/")
@login_required
def index():
    expenses = list(expenses_collection.find({"user_id": current_user.id}))
    total = sum(exp["amount"] for exp in expenses)
    user_doc = users_collection.find_one({"_id": ObjectId(current_user.id)})
    return render_template("index.html", expenses=expenses, total=total, user=user_doc)


@app.route("/add", methods=["POST"])
@login_required
def add_expense():
    amount = float(request.form["amount"])
    category = request.form["category"]
    date = request.form["date"] or datetime.today().strftime("%Y-%m-%d")
    expense = {
        "amount": amount,
        "category": category,
        "date": date,
        "user_id": current_user.id,
    }
    expenses_collection.insert_one(expense)
    return redirect(url_for("index"))


@app.route("/edit/<id>", methods=["GET", "POST"])
@login_required
def edit_expense(id):
    expense = expenses_collection.find_one(
        {"_id": ObjectId(id), "user_id": current_user.id}
    )
    if not expense:
        return "❌ Access Denied"
    if request.method == "POST":
        updated = {
            "amount": float(request.form["amount"]),
            "category": request.form["category"],
            "date": request.form["date"],
        }
        expenses_collection.update_one(
            {"_id": ObjectId(id), "user_id": current_user.id}, {"$set": updated}
        )
        return redirect(url_for("index"))

    user_doc = users_collection.find_one({"_id": ObjectId(current_user.id)})
    return render_template("edit.html", expense=expense, user=user_doc)


@app.route("/delete/<id>")
@login_required
def delete_expense(id):
    expenses_collection.delete_one({"_id": ObjectId(id), "user_id": current_user.id})
    return redirect(url_for("index"))


@app.route("/summary")
@login_required
def summary():
    expenses = list(expenses_collection.find({"user_id": current_user.id}))
    total = sum(e["amount"] for e in expenses)
    by_category = defaultdict(float)
    by_day = defaultdict(float)
    by_month = defaultdict(float)
    for e in expenses:
        by_category[e["category"]] += e["amount"]
        by_day[e["date"]] += e["amount"]
        by_month[e["date"][:7]] += e["amount"]
    user_doc = users_collection.find_one({"_id": ObjectId(current_user.id)})
    return render_template(
        "summary.html",
        total=total,
        by_category=by_category,
        by_day=by_day,
        by_month=by_month,
        user=user_doc,  # ✅ Add this
    )


@app.route("/visualize")
@login_required
def visualize():
    expenses = list(expenses_collection.find({"user_id": current_user.id}))
    categories = defaultdict(float)
    for e in expenses:
        categories[e["category"]] += e["amount"]
    labels = list(categories.keys())
    values = list(categories.values())

    # Bar Chart
    plt.figure(figsize=(10, 6))
    plt.bar(labels, values, color="teal")
    plt.title("Expenses by Category")
    plt.xlabel("Category")
    plt.ylabel("Total (₹)")
    plt.tight_layout()
    bar_img = io.BytesIO()
    plt.savefig(bar_img, format="png", facecolor="lightgray")
    bar_img.seek(0)
    bar_chart = base64.b64encode(bar_img.getvalue()).decode()
    plt.close()

    # Pie Chart
    plt.figure(figsize=(7, 7))
    plt.pie(
        values,
        labels=labels,
        autopct="%1.1f%%",
        colors=plt.cm.Set3.colors,
        startangle=140,
    )
    plt.title("Expense Distribution (Pie Chart)")
    plt.tight_layout()
    pie_img = io.BytesIO()
    plt.savefig(pie_img, format="png", facecolor="white")
    pie_img.seek(0)
    pie_chart = base64.b64encode(pie_img.getvalue()).decode()
    plt.close()

    user_doc = users_collection.find_one({"_id": ObjectId(current_user.id)})
    return render_template(
        "visualize.html", bar_chart=bar_chart, pie_chart=pie_chart, user=user_doc
    )


# Make sure this line is added somewhere at the top of your app.py
app.config["UPLOAD_FOLDER"] = "static/profile_pics"


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_doc = db.users.find_one({"_id": ObjectId(current_user.id)})

    if request.method == "POST":
        name = request.form.get("name")
        new_password = request.form.get("password")
        profile_pic = request.files.get("profile_pic")
        update_data = {}

        # 🔹 Update name
        if name:
            update_data["name"] = name

        # 🔹 Update password
        if new_password:
            hashed = bcrypt.generate_password_hash(new_password).decode("utf-8")
            update_data["password"] = hashed

        # 🔹 Update profile picture
        if profile_pic and profile_pic.filename:
            filename = secure_filename(profile_pic.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            profile_pic.save(filepath)
            update_data["profile_pic"] = filename

        # 🔹 Save changes if any
        if update_data:
            db.users.update_one(
                {"_id": ObjectId(current_user.id)}, {"$set": update_data}
            )
            return redirect(url_for("profile"))

    return render_template("profile.html", user=user_doc)


# === Auth Routes ===


from flask import flash  # Make sure this is imported at the top

import re  # Add this at the top of your file for regex


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip()
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        # 1. All fields required
        if not name or not email or not password or not confirm_password:
            flash("❌ All fields are required.", "danger")
            return redirect(url_for("register"))

        # 2. Email must be valid & end with @gmail.com
        email_pattern = r"^[\w\.-]+@gmail\.com$"
        if not re.match(email_pattern, email):
            flash(
                "❌ Email must be a valid Gmail address (e.g., example@gmail.com).",
                "danger",
            )
            return redirect(url_for("register"))

        # 3. Password validation: min 8 chars, 1 uppercase, 1 special char
        password_pattern = r"^(?=.*[A-Z])(?=.*[\W_]).{8,}$"
        if not re.match(password_pattern, password):
            flash(
                "❌ Password must be at least 8 characters with 1 uppercase letter and 1 special character.",
                "danger",
            )
            return redirect(url_for("register"))

        # 4. Passwords must match
        if password != confirm_password:
            flash("❌ Passwords do not match.", "danger")
            return redirect(url_for("register"))

        # 5. Check if email already exists
        if users_collection.find_one({"email": email}):
            flash("⚠️ A user with this email already exists. Try logging in.", "warning")
            return redirect(url_for("register"))

        # 6. Register user
        hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")
        users_collection.insert_one(
            {
                "name": name,
                "email": email,
                "password": hashed_pw,
                "profile_pic": "default.png",
                "created_at": datetime.utcnow(),
            }
        )

        flash("✅ Registered successfully! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user_doc = users_collection.find_one({"email": email})
        if user_doc and bcrypt.check_password_hash(user_doc["password"], password):
            login_user(User(user_doc))
            return redirect(url_for("index"))
        return "Invalid credentials"
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = request.form["email"]
        user = users_collection.find_one({"email": email})
        if user:
            token = s.dumps(email, salt="reset-password")
            link = url_for("reset_password", token=token, _external=True)
            return f"Password reset link (simulated): <a href='{link}'>{link}</a>"
        return "Email not found"
    return render_template("forgot_password.html")


@app.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        email = s.loads(token, salt="reset-password", max_age=600)
    except:
        return "Invalid or expired token"
    if request.method == "POST":
        new_password = request.form["password"]
        hashed = bcrypt.generate_password_hash(new_password).decode("utf-8")
        users_collection.update_one({"email": email}, {"$set": {"password": hashed}})
        return redirect(url_for("login"))
    return render_template("reset_password.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # 👈 Use the PORT from environment
    app.run(host="0.0.0.0", port=port)

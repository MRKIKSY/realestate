import os
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from urllib.parse import quote_plus
from flask_sqlalchemy import SQLAlchemy

from dotenv import load_dotenv
load_dotenv()


# ---------------- CONFIG ---------------- #
UPLOAD_FOLDER = "uploads"
ALLOWED_EXT = {"pdf", "png", "jpg", "jpeg"}
WHATSAPP_TO = "2347077513836"
ADMIN_SECRET = "KINGSCAB_ADMIN_2025"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, static_folder=".", static_url_path="/")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

# ✅ DATABASE SETUP
# Render provides DATABASE_URL (PostgreSQL) in env vars
db_url = os.getenv("DATABASE_URL", "sqlite:///local.db").replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------------- MODELS ---------------- #
class Listing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    rent = db.Column(db.Integer)
    location = db.Column(db.String(255))
    owner_name = db.Column(db.String(255), nullable=False)
    owner_email = db.Column(db.String(255), nullable=False)
    owner_phone = db.Column(db.String(50), nullable=False)
    proof_filename = db.Column(db.String(255))
    property_images = db.Column(db.Text)
    is_verified = db.Column(db.Boolean, default=False)
    contact_clicks = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Enquiry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listing.id"))
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    whatsapp_url = db.Column(db.String(500))

# ---------------- HELPERS ---------------- #
def allowed_file(filename):
    ext = filename.rsplit(".", 1)[-1].lower()
    return "." in filename and ext in ALLOWED_EXT

# ---------------- ROUTES ---------------- #

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/admin")
def admin_page():
    key = request.args.get("key", "")
    if key != ADMIN_SECRET:
        return "Unauthorized: provide correct admin key as ?key=...", 403
    return send_from_directory(".", "admin.html")

@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# ---------- CREATE LISTING ----------
@app.route("/api/listings", methods=["POST"])
def create_listing():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    rent = request.form.get("rent", "").strip()
    location = request.form.get("location", "").strip()
    owner_name = request.form.get("owner_name", "").strip()
    owner_email = request.form.get("owner_email", "").strip()
    owner_phone = request.form.get("owner_phone", "").strip()

    if not (title and owner_name and owner_email and owner_phone):
        return jsonify({"error": "Missing required fields."}), 400

    # Save proof file
    proof_filename = None
    proof_file = request.files.get("proofFile")
    if proof_file and proof_file.filename:
        if not allowed_file(proof_file.filename):
            return jsonify({"error": "Invalid file type for proof"}), 400
        filename = secure_filename(f"{int(datetime.utcnow().timestamp())}_proof_{proof_file.filename}")
        proof_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
        proof_filename = filename

    # Save property images
    image_files = request.files.getlist("propertyImages")
    image_filenames = []
    for img in image_files:
        if img and allowed_file(img.filename):
            filename = secure_filename(f"{int(datetime.utcnow().timestamp())}_img_{img.filename}")
            img.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            image_filenames.append(filename)

    try:
        rent_val = int(rent) if rent else None
    except ValueError:
        return jsonify({"error": "Rent must be an integer"}), 400

    listing = Listing(
        title=title,
        description=description,
        rent=rent_val,
        location=location,
        owner_name=owner_name,
        owner_email=owner_email,
        owner_phone=owner_phone,
        proof_filename=proof_filename,
        property_images=",".join(image_filenames),
    )
    db.session.add(listing)
    db.session.commit()

    return jsonify({"message": "Listing created", "listing_id": listing.id}), 201

# ---------- PUBLIC LISTINGS ----------
@app.route("/api/listings", methods=["GET"])
def list_listings():
    q = request.args.get("q", "").strip()
    query = Listing.query
    if q:
        query = query.filter(
            (Listing.title.ilike(f"%{q}%"))
            | (Listing.description.ilike(f"%{q}%"))
            | (Listing.location.ilike(f"%{q}%"))
        )
    listings = query.order_by(Listing.created_at.desc()).all()
    return jsonify([
        {
            "id": l.id,
            "title": l.title,
            "description": l.description,
            "rent": l.rent,
            "location": l.location,
            "is_verified": l.is_verified,
            "contact_clicks": l.contact_clicks,
            "created_at": l.created_at.isoformat(),
            "property_images": l.property_images,
        } for l in listings
    ])

# ---------- ENQUIRIES ----------
@app.route("/api/enquiry/<int:listing_id>", methods=["POST"])
def create_enquiry(listing_id):
    data = request.get_json() or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    listing = Listing.query.get(listing_id)
    if not listing:
        return jsonify({"error": "listing not found"}), 404

    listing.contact_clicks += 1
    text = f"Enquiry about listing #{listing_id}: {listing.title}. {listing.description or ''}\n\nMessage:\n{message}"
    encoded = quote_plus(text)
    wa_url = f"https://wa.me/{WHATSAPP_TO}?text={encoded}"

    enquiry = Enquiry(listing_id=listing_id, message=message, whatsapp_url=wa_url)
    db.session.add(enquiry)
    db.session.commit()

    return jsonify({"whatsapp_url": wa_url}), 201

# ---------- ADMIN ----------
@app.route("/api/admin/listings", methods=["GET"])
def admin_listings():
    key = request.args.get("key", "")
    if key != ADMIN_SECRET:
        return jsonify({"error": "unauthorized"}), 403
    listings = Listing.query.order_by(Listing.created_at.desc()).all()
    return jsonify([{
        "id": l.id,
        "title": l.title,
        "description": l.description,
        "rent": l.rent,
        "location": l.location,
        "is_verified": l.is_verified,
        "contact_clicks": l.contact_clicks,
        "created_at": l.created_at.isoformat(),
        "proof_filename": l.proof_filename,
        "property_images": l.property_images,
    } for l in listings])

@app.route("/api/admin/verify/<int:listing_id>", methods=["POST"])
def admin_verify(listing_id):
    key = request.args.get("key", "")
    if key != ADMIN_SECRET:
        return jsonify({"error": "unauthorized"}), 403
    listing = Listing.query.get(listing_id)
    if not listing:
        return jsonify({"error": "not found"}), 404
    listing.is_verified = True
    db.session.commit()
    return jsonify({"message": "verified"})

@app.route("/api/admin/unverify/<int:listing_id>", methods=["POST"])
def admin_unverify(listing_id):
    key = request.args.get("key", "")
    if key != ADMIN_SECRET:
        return jsonify({"error": "unauthorized"}), 403
    listing = Listing.query.get(listing_id)
    if not listing:
        return jsonify({"error": "not found"}), 404
    listing.is_verified = False
    db.session.commit()
    return jsonify({"message": "unverified"})

@app.route("/api/admin/delete/<int:listing_id>", methods=["POST"])
def admin_delete(listing_id):
    key = request.args.get("key", "")
    if key != ADMIN_SECRET:
        return jsonify({"error": "unauthorized"}), 403
    listing = Listing.query.get(listing_id)
    if not listing:
        return jsonify({"error": "not found"}), 404

    # Delete uploaded files
    files_to_delete = []
    if listing.proof_filename:
        files_to_delete.append(listing.proof_filename)
    if listing.property_images:
        files_to_delete.extend(listing.property_images.split(","))

    for f in files_to_delete:
        try:
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], f))
        except Exception:
            pass

    Enquiry.query.filter_by(listing_id=listing_id).delete()
    db.session.delete(listing)
    db.session.commit()
    return jsonify({"message": "deleted"})

# ---------------- MAIN ---------------- #
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5000)

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Literal

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tsec.db")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", "http://localhost:8000").rstrip("/")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
logger = logging.getLogger(__name__)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(32), default="demo")
    provider_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="pending")
    graduation_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    branch: Mapped[str | None] = mapped_column(String(80), nullable=True)
    company: Mapped[str | None] = mapped_column(String(120), nullable=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    skills: Mapped[str] = mapped_column(String(500), default="")
    linkedin: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class PostBase:
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Job(PostBase, Base):
    __tablename__ = "jobs"
    company: Mapped[str] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(120))
    apply_url: Mapped[str | None] = mapped_column(String(500), nullable=True)


class JobApplication(Base):
    __tablename__ = "job_applications"
    __table_args__ = (UniqueConstraint("job_id", "applicant_id", name="uq_job_application_applicant"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    applicant_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Event(PostBase, Base):
    __tablename__ = "events"
    status: Mapped[str] = mapped_column(String(20), default="pending")
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    venue: Mapped[str] = mapped_column(String(180))


class ContactRequest(Base):
    __tablename__ = "contact_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Donation(Base):
    __tablename__ = "donations"
    id: Mapped[int] = mapped_column(primary_key=True)
    donor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    amount: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), default="created")
    provider_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    graduation_year: int | None = Field(default=None, ge=1950, le=2100)
    branch: str | None = None
    company: str | None = None
    title: str | None = None
    location: str | None = None
    bio: str | None = Field(default=None, max_length=1000)
    skills: str = ""
    linkedin: str | None = None


class ContactIn(BaseModel):
    recipient_id: int
    message: str = Field(min_length=3, max_length=1000)


class PostIn(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    description: str = Field(min_length=5, max_length=3000)
    company: str | None = None
    location: str | None = None
    apply_url: str | None = None
    starts_at: datetime | None = None
    venue: str | None = None


class JobApplicationIn(BaseModel):
    message: str = Field(min_length=10, max_length=2000)


class DonationIn(BaseModel):
    amount: int = Field(ge=100, le=1000000)
    purpose: str = Field(min_length=2, max_length=160)


class PaymentVerificationIn(BaseModel):
    razorpay_order_id: str = Field(min_length=1, max_length=120)
    razorpay_payment_id: str = Field(min_length=1, max_length=120)
    razorpay_signature: str = Field(min_length=1, max_length=256)


def public_user(user: User, viewer: User | None = None):
    verified = viewer and viewer.role in {"verified", "admin"}
    return {"id": user.id, "name": user.name, "email": user.email if verified else None,
            "graduation_year": user.graduation_year, "branch": user.branch, "company": user.company,
            "title": user.title, "location": user.location, "bio": user.bio, "skills": user.skills,
            "linkedin": user.linkedin, "role": user.role if viewer and viewer.id == user.id else None}


def get_db():
    with SessionLocal() as db:
        yield db


def current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(401, "Sign in required")
    user = db.get(User, user_id)
    if not user:
        request.session.clear()
        raise HTTPException(401, "Session expired")
    return user


def optional_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    return db.get(User, user_id) if user_id else None


def verified_user(user: User = Depends(current_user)):
    if user.role not in {"verified", "admin"}:
        raise HTTPException(403, "Alumni verification required")
    return user


def admin_user(user: User = Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    return user


oauth = OAuth()
if os.getenv("GOOGLE_CLIENT_ID"):
    oauth.register("google", client_id=os.environ["GOOGLE_CLIENT_ID"], client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
                   server_metadata_url="https://accounts.google.com/.well-known/openid-configuration", client_kwargs={"scope": "openid email profile"})
if os.getenv("MICROSOFT_CLIENT_ID"):
    oauth.register("microsoft", client_id=os.environ["MICROSOFT_CLIENT_ID"], client_secret=os.environ["MICROSOFT_CLIENT_SECRET"],
                   server_metadata_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration", client_kwargs={"scope": "openid email profile User.Read"})

app = FastAPI(title="TSEC Alumni Connect")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "development-only-change-me"), same_site="lax", https_only=False)
app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND_ORIGIN], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def ensure_user(db: Session, email: str, name: str, provider: str, subject: str | None):
    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user:
        admins = {x.strip().lower() for x in os.getenv("BOOTSTRAP_ADMIN_EMAILS", "admin@tsec.edu").split(",")}
        user = User(email=email.lower(), name=name, provider=provider, provider_subject=subject, role="admin" if email.lower() in admins else "pending")
        db.add(user); db.commit(); db.refresh(user)
    return user


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)):
            return
        admin = User(email="admin@tsec.edu", name="Dr. Ananya Shah", role="admin", provider="seed", branch="Computer Engineering", graduation_year=2004, company="TSEC", title="Alumni Relations Lead", location="Mumbai")
        alumni = [
            User(email="riya.mehta@example.com", name="Riya Mehta", role="verified", provider="seed", graduation_year=2017, branch="Computer Engineering", company="Fictional Labs", title="Product Manager", location="Mumbai", skills="Product strategy, SaaS, mentoring"),
            User(email="arjun.nair@example.com", name="Arjun Nair", role="verified", provider="seed", graduation_year=2014, branch="Information Technology", company="Nimbus Systems", title="Engineering Manager", location="Bengaluru", skills="Python, cloud, hiring"),
            User(email="sana.khan@example.com", name="Sana Khan", role="verified", provider="seed", graduation_year=2019, branch="Electronics", company="CircuitWorks", title="Hardware Engineer", location="Pune", skills="IoT, embedded systems"),
        ]
        db.add_all([admin, *alumni]); db.flush()
        db.add_all([
            Job(title="Backend Engineer", description="Help build reliable data products with a supportive alumni team.", company="Nimbus Systems", location="Bengaluru / Hybrid", author_id=admin.id, apply_url="https://example.com/jobs"),
            Job(title="Product Design Intern", description="A paid summer internship for students who love thoughtful product craft.", company="Fictional Labs", location="Mumbai", author_id=admin.id),
            Event(title="TSEC Alumni Homecoming 2026", description="Reconnect with classmates, mentors, and the next generation of TSEC builders.", venue="TSEC Campus, Bandra", starts_at=datetime(2026, 8, 22, 17, 0), author_id=admin.id, status="approved"),
        ])
        db.commit()


@app.get("/health")
def health(): return {"ok": True}


@app.get("/auth/{provider}")
async def login(provider: Literal["google", "microsoft"], request: Request):
    client = oauth.create_client(provider)
    if not client: raise HTTPException(503, f"{provider.title()} sign-in is not configured")
    # Vite forwards the browser Host header in development. Use the explicit API
    # origin so the provider callback always matches its registered URI.
    callback_url = f"{API_PUBLIC_URL}/auth/{provider}/callback"
    return await client.authorize_redirect(request, callback_url)


@app.get("/auth/{provider}/callback", name="auth_callback")
async def auth_callback(provider: Literal["google", "microsoft"], request: Request, db: Session = Depends(get_db)):
    client = oauth.create_client(provider)
    token = await client.authorize_access_token(request)
    info = token.get("userinfo") or await client.userinfo(token=token)
    email = info.get("email") or info.get("preferred_username")
    if not email: raise HTTPException(400, "Provider did not supply an email address")
    user = ensure_user(db, email, info.get("name") or email.split("@")[0], provider, info.get("sub"))
    request.session["user_id"] = user.id
    return RedirectResponse(FRONTEND_ORIGIN)


@app.post("/auth/demo-login")
def demo_login(request: Request, email: EmailStr, db: Session = Depends(get_db)):
    if not DEMO_MODE: raise HTTPException(404, "Demo login disabled")
    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user: raise HTTPException(404, "Choose a seeded demo user")
    request.session["user_id"] = user.id
    return public_user(user, user)


@app.post("/auth/logout")
def logout(request: Request): request.session.clear(); return {"ok": True}

@app.get("/me")
def me(user: User = Depends(current_user)): return public_user(user, user)

@app.put("/me")
def update_me(data: ProfileIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    for key, value in data.model_dump().items(): setattr(user, key, value)
    db.commit(); db.refresh(user); return public_user(user, user)


@app.get("/alumni")
def alumni(q: str = "", branch: str = "", year: int | None = None, db: Session = Depends(get_db), viewer: User | None = Depends(optional_user)):
    stmt = select(User).where(User.role.in_(["verified", "admin"]))
    if q: stmt = stmt.where((User.name.ilike(f"%{q}%")) | (User.company.ilike(f"%{q}%")) | (User.skills.ilike(f"%{q}%")))
    if branch: stmt = stmt.where(User.branch.ilike(f"%{branch}%"))
    if year: stmt = stmt.where(User.graduation_year == year)
    return [public_user(x, viewer) for x in db.scalars(stmt.order_by(User.name)).all()]


@app.get("/jobs")
def jobs(db: Session = Depends(get_db)): return [{"id": x.id, "title": x.title, "description": x.description, "company": x.company, "location": x.location, "apply_url": x.apply_url} for x in db.scalars(select(Job).order_by(Job.created_at.desc())).all()]

@app.post("/jobs")
def create_job(data: PostIn, db: Session = Depends(get_db), user: User = Depends(verified_user)):
    if not data.company or not data.location: raise HTTPException(422, "Company and location are required")
    item = Job(title=data.title, description=data.description, company=data.company, location=data.location, apply_url=data.apply_url, author_id=user.id)
    db.add(item); db.commit(); return {"id": item.id}


@app.post("/jobs/{job_id}/applications")
def apply_for_job(job_id: int, data: JobApplicationIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not db.get(Job, job_id):
        raise HTTPException(404, "Job not found")
    if db.scalar(select(JobApplication.id).where(JobApplication.job_id == job_id, JobApplication.applicant_id == user.id)):
        raise HTTPException(409, "You have already applied for this job")
    application = JobApplication(job_id=job_id, applicant_id=user.id, message=data.message)
    db.add(application); db.commit()
    return {"id": application.id, "status": "submitted"}


@app.get("/events")
def events(db: Session = Depends(get_db)): return [{"id": x.id, "title": x.title, "description": x.description, "venue": x.venue, "starts_at": x.starts_at, "status": x.status} for x in db.scalars(select(Event).where(Event.status == "approved").order_by(Event.starts_at)).all()]

@app.post("/events")
def create_event(data: PostIn, db: Session = Depends(get_db), user: User = Depends(verified_user)):
    if not data.starts_at or not data.venue: raise HTTPException(422, "Date and venue are required")
    item = Event(title=data.title, description=data.description, starts_at=data.starts_at, venue=data.venue, author_id=user.id)
    db.add(item); db.commit(); return {"id": item.id, "status": item.status}


@app.post("/contact-requests")
def send_request(data: ContactIn, db: Session = Depends(get_db), user: User = Depends(verified_user)):
    if data.recipient_id == user.id: raise HTTPException(400, "You cannot contact yourself")
    if not db.get(User, data.recipient_id): raise HTTPException(404, "Alum not found")
    item = ContactRequest(sender_id=user.id, recipient_id=data.recipient_id, message=data.message)
    db.add(item); db.commit(); return {"id": item.id, "status": item.status}


@app.get("/contact-requests")
def contact_requests(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(ContactRequest).where((ContactRequest.sender_id == user.id) | (ContactRequest.recipient_id == user.id)).order_by(ContactRequest.created_at.desc())).all()
    return [{"id": x.id, "message": x.message, "status": x.status, "incoming": x.recipient_id == user.id, "counterpart": public_user(db.get(User, x.sender_id if x.recipient_id == user.id else x.recipient_id), user)} for x in rows]


@app.post("/contact-requests/{request_id}/{decision}")
def decide_request(request_id: int, decision: Literal["accepted", "declined"], db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = db.get(ContactRequest, request_id)
    if not item or item.recipient_id != user.id: raise HTTPException(404, "Request not found")
    item.status = decision; db.commit(); return {"id": item.id, "status": item.status}


@app.post("/donations/order")
def donation_order(data: DonationIn, db: Session = Depends(get_db), user: User | None = Depends(optional_user)):
    item = Donation(donor_id=user.id if user else None, amount=data.amount, purpose=data.purpose, status="created")
    key_id, secret = os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")
    if key_id and secret:
        import razorpay
        try:
            order = razorpay.Client(auth=(key_id, secret)).order.create({"amount": data.amount * 100, "currency": "INR", "receipt": f"tsec-{int(datetime.now().timestamp())}"})
        except Exception as exc:
            # Do not expose provider responses: they can contain request metadata.
            # A 503 from Razorpay is upstream availability, not a browser checkout error.
            logger.exception("Razorpay order creation failed")
            status_code = getattr(exc, "status_code", None)
            if status_code and 400 <= status_code < 500:
                raise HTTPException(400, "Razorpay rejected the test-key request. Check that both test keys belong to the same account.") from exc
            raise HTTPException(502, "Razorpay is temporarily unavailable. Please try again shortly.") from exc
        item.provider_order_id = order["id"]
        db.add(item); db.commit()
        return {"donation_id": item.id, "provider": "razorpay", "key_id": key_id, "order_id": order["id"], "amount": order["amount"]}
    item.status = "demo_paid"; db.add(item); db.commit()
    return {"donation_id": item.id, "provider": "demo", "amount": data.amount * 100}


@app.post("/donations/verify")
def verify_donation(data: PaymentVerificationIn, db: Session = Depends(get_db)):
    """Verify the Checkout.js signature before marking a donation as paid."""
    secret = os.getenv("RAZORPAY_KEY_SECRET")
    if not secret:
        raise HTTPException(503, "Razorpay is not configured")
    donation = db.scalar(select(Donation).where(Donation.provider_order_id == data.razorpay_order_id))
    if not donation:
        raise HTTPException(404, "Donation order not found")
    expected = hmac.new(
        secret.encode(),
        f"{data.razorpay_order_id}|{data.razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, data.razorpay_signature):
        raise HTTPException(400, "Payment signature verification failed")
    donation.status = "paid"
    db.commit()
    return {"donation_id": donation.id, "status": donation.status}


@app.get("/admin/pending")
def pending(db: Session = Depends(get_db), _: User = Depends(admin_user)):
    users = db.scalars(select(User).where(User.role == "pending").order_by(User.created_at.desc())).all()
    events = db.scalars(select(Event).where(Event.status == "pending").order_by(Event.starts_at)).all()
    return {
        "users": [{"id": x.id, "name": x.name, "email": x.email, "graduation_year": x.graduation_year,
                   "branch": x.branch, "company": x.company, "title": x.title, "location": x.location,
                   "bio": x.bio, "skills": x.skills, "linkedin": x.linkedin, "created_at": x.created_at} for x in users],
        "events": [{"id": x.id, "title": x.title, "description": x.description, "venue": x.venue,
                    "starts_at": x.starts_at, "created_at": x.created_at,
                    "author": {"id": author.id, "name": author.name, "email": author.email} if (author := db.get(User, x.author_id)) else None} for x in events],
    }


@app.post("/admin/users/{user_id}/{decision}")
def review_user(user_id: int, decision: Literal["verified", "rejected"], db: Session = Depends(get_db), _: User = Depends(admin_user)):
    target = db.get(User, user_id)
    if not target: raise HTTPException(404, "User not found")
    if target.role != "pending": raise HTTPException(409, "Only pending alumni can be reviewed")
    target.role = decision; db.commit(); return public_user(target, target)


@app.post("/admin/events/{item_id}/{decision}")
def moderate_event(item_id: int, decision: Literal["approved", "rejected"], db: Session = Depends(get_db), _: User = Depends(admin_user)):
    item = db.get(Event, item_id)
    if not item: raise HTTPException(404, "Item not found")
    if item.status != "pending": raise HTTPException(409, "Only pending events can be reviewed")
    item.status = decision; db.commit(); return {"id": item.id, "status": item.status}

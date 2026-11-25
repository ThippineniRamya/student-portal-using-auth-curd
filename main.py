from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session

from database import get_db, Base, engine
from model import User, Student
from security import hash_password, verify_password

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

Base.metadata.create_all(bind=engine)

# Session Middleware
app.add_middleware(
    SessionMiddleware,
    secret_key="fsd_batch_64_python",
    max_age=300,
    same_site="lax",
    https_only=False
)


# Home Page
@app.get("/")
def home(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="home.html"
    )


# Register Page
@app.get("/register")
def register_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"error": None}
    )


# Register User
@app.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):

    # Check if email already exists
    existing_user = db.query(User).filter(
        User.email == email
    ).first()

    if existing_user:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Email already registered"}
        )

    # Hash password
    hashed_password = hash_password(password)

    # Create user
    new_user = User(
        email=email,
        password_hash=hashed_password
    )

    # Save user in database
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return RedirectResponse(
        "/login",
        status_code=303
    )


# Login Page
@app.get("/login")
def login_page(request: Request):

    # Already logged in
    if request.session.get("user_id"):
        return RedirectResponse(
            "/dashboard",
            status_code=303
        )

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": None}
    )


# Login User
@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):

    # Find user
    user = db.query(User).filter(
        User.email == email
    ).first()

    # Check user exists
    if user is None:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid email or password"}
        )

    # Verify password
    if not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid email or password"}
        )

    # Create session
    request.session["user_id"] = user.id
    request.session["email"] = user.email
    request.session["visit_count"] = 0

    return RedirectResponse(
        "/dashboard",
        status_code=303
    )


# Dashboard (list + search + add form)
@app.get("/dashboard")
def dashboard(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db)
):

    # Check login
    if "user_id" not in request.session:
        return RedirectResponse(
            "/login",
            status_code=303
        )

    # Get session data
    email = request.session["email"]
    user_id = request.session["user_id"]

    # Increase visit count
    request.session["visit_count"] = request.session.get("visit_count", 0) + 1

    visits = request.session["visit_count"]

    # READ: only this user's students, optionally filtered by search text
    query = db.query(Student).filter(Student.owner_id == user_id)

    q = q.strip()
    if q:
        like = f"%{q}%"
        query = query.filter(
            Student.name.ilike(like)
            | Student.email.ilike(like)
            | Student.course.ilike(like)
        )

    students = query.order_by(Student.id.desc()).all()

    total_students = db.query(Student).filter(
        Student.owner_id == user_id
    ).count()

    # One-time message (set by add / edit / delete)
    flash = request.session.pop("flash", None)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "email": email,
            "user_id": user_id,
            "visits": visits,
            "students": students,
            "total_students": total_students,
            "q": q,
            "flash": flash
        }
    )


def parse_age(age_text: str):
    """Return (age, error). Empty age is allowed."""
    age_text = age_text.strip()

    if age_text == "":
        return None, None

    if not age_text.isdigit() or not (1 <= int(age_text) <= 120):
        return None, "Age must be a number between 1 and 120"

    return int(age_text), None


# CREATE
@app.post("/students/add")
def add_student(
    request: Request,
    name: str = Form(...),
    student_email: str = Form(...),
    course: str = Form(...),
    age: str = Form(""),
    db: Session = Depends(get_db)
):

    if "user_id" not in request.session:
        return RedirectResponse("/login", status_code=303)

    age_value, age_error = parse_age(age)

    if age_error:
        request.session["flash"] = {"type": "error", "text": age_error}
        return RedirectResponse("/dashboard", status_code=303)

    student = Student(
        owner_id=request.session["user_id"],
        name=name.strip(),
        email=student_email.strip(),
        course=course.strip(),
        age=age_value
    )

    db.add(student)
    db.commit()

    request.session["flash"] = {
        "type": "success",
        "text": f"Student '{student.name}' added"
    }

    return RedirectResponse("/dashboard", status_code=303)


# UPDATE - show edit form
@app.get("/students/{student_id}/edit")
def edit_student_page(
    request: Request,
    student_id: int,
    db: Session = Depends(get_db)
):

    if "user_id" not in request.session:
        return RedirectResponse("/login", status_code=303)

    # Only the owner can open their own record
    student = db.query(Student).filter(
        Student.id == student_id,
        Student.owner_id == request.session["user_id"]
    ).first()

    if student is None:
        request.session["flash"] = {
            "type": "error",
            "text": "Student not found"
        }
        return RedirectResponse("/dashboard", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="edit_student.html",
        context={"student": student, "error": None}
    )


# UPDATE - save changes
@app.post("/students/{student_id}/edit")
def edit_student(
    request: Request,
    student_id: int,
    name: str = Form(...),
    student_email: str = Form(...),
    course: str = Form(...),
    age: str = Form(""),
    db: Session = Depends(get_db)
):

    if "user_id" not in request.session:
        return RedirectResponse("/login", status_code=303)

    student = db.query(Student).filter(
        Student.id == student_id,
        Student.owner_id == request.session["user_id"]
    ).first()

    if student is None:
        request.session["flash"] = {
            "type": "error",
            "text": "Student not found"
        }
        return RedirectResponse("/dashboard", status_code=303)

    age_value, age_error = parse_age(age)

    if age_error:
        return templates.TemplateResponse(
            request=request,
            name="edit_student.html",
            context={"student": student, "error": age_error}
        )

    student.name = name.strip()
    student.email = student_email.strip()
    student.course = course.strip()
    student.age = age_value

    db.commit()

    request.session["flash"] = {
        "type": "success",
        "text": f"Student '{student.name}' updated"
    }

    return RedirectResponse("/dashboard", status_code=303)


# DELETE
@app.post("/students/{student_id}/delete")
def delete_student(
    request: Request,
    student_id: int,
    db: Session = Depends(get_db)
):

    if "user_id" not in request.session:
        return RedirectResponse("/login", status_code=303)

    student = db.query(Student).filter(
        Student.id == student_id,
        Student.owner_id == request.session["user_id"]
    ).first()

    if student is None:
        request.session["flash"] = {
            "type": "error",
            "text": "Student not found"
        }
    else:
        name = student.name
        db.delete(student)
        db.commit()
        request.session["flash"] = {
            "type": "success",
            "text": f"Student '{name}' deleted"
        }

    return RedirectResponse("/dashboard", status_code=303)


# Logout
@app.get("/logout")
def logout(request: Request):

    # Clear session
    request.session.clear()

    return RedirectResponse(
        "/",
        status_code=303
    )

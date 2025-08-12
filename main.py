import base64
import io
import bcrypt
from fastapi import Form
import fitz  # PyMuPDF
import os
import time
from fastapi import FastAPI, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo import MongoClient
import google.generativeai as genai

# ================== CONFIG ======================
MONGO_URI = "mongodb+srv://skillzage1:0vwfCt2zjV1fq0h1@cluster0.gcbclzb.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DB_NAME = "resume_analyzer"
COLLECTION_NAME = "prompts"
LITE_PROMPTS_COLLECTION = "lite_prompts"


client = MongoClient(MONGO_URI)
db = client[DB_NAME]
prompt_collection = db[COLLECTION_NAME]
logs_collection = db["resume_logs"]  # Store logs
users_collection = db["users"]
lite_prompts_collection = db[LITE_PROMPTS_COLLECTION]
# ================== CONFIG END ==================


ADMIN_TOKEN = "drdoom"

genai.configure(api_key="AIzaSyCcoQ40u_iM1BIvp26iLqVTWdHp3Ky0TAw")

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# @app.get("/migrate_data")
# def migrate_data_to_client():
#     try:
#         # Ideally use environment variables or a config file
#         SOURCE_URI = "mongodb+srv://ayushsuryavanshi03:tSM6nbQBtNkkM8uO@cluster0.i9n9dqa.mongodb.net/?retryWrites=true&w=majority"
#         DEST_URI = "mongodb+srv://skillzage1:0vwfCt2zjV1fq0h1@cluster0.gcbclzb.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

#         COLLECTIONS = ["prompts", "resume_logs", "users"]

#         src_client = MongoClient(SOURCE_URI)
#         dst_client = MongoClient(DEST_URI)

#         src_db = src_client["resume_analyzer"]
#         dst_db = dst_client["resume_analyzer"]

#         result = {}

#         for name in COLLECTIONS:
#             src_col = src_db[name]
#             dst_col = dst_db[name]

#             data = list(src_col.find({}))
#             for doc in data:
#                 doc.pop("_id", None)

#             if data:
#                 dst_col.delete_many({})  # Optional: remove if you want to merge instead of overwrite
#                 dst_col.insert_many(data)
#                 result[name] = f"Migrated {len(data)} documents"
#             else:
#                 result[name] = "No documents to migrate"

#         # Close connections
#         src_client.close()
#         dst_client.close()

#         return {"status": "success", "details": result}

#     except Exception as e:
#         return {"status": "error", "message": str(e)}


# =============== DATABASE LOGIC =================
# @app.get("/create_admin_once")
# def create_admin_once():
#     if users_collection.find_one({"username": "admin"}):
#         return {"status": "User already exists"}

#     hashed_pw = bcrypt.hashpw("drdoom".encode(), bcrypt.gensalt()).decode()
#     users_collection.insert_one({
#         "username": "admin",
#         "password": hashed_pw,
#         "role": "Administrator"
#     })
#     return {"status": "Admin user created"}

# ============== ADMIN ROUTES LoginLogic ======================


class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/login")
def login(data: LoginRequest):
    user = users_collection.find_one({"username": data.username})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    if bcrypt.checkpw(data.password.encode(), user["password"].encode()):
        return {"status": True, "role": user.get("role", "User")}
    else:
        raise HTTPException(status_code=401, detail="Invalid username or password")


#==========ForgotPassword============


@app.post("/forgot_password")
def forgot_password(email: str = Form(...)):
    user = users_collection.find_one({"email": email})
    if not user:
        return {"status": False, "message": "User not found with this email."}
    
    # TEMP: For now, just return this instead of sending email
    return {"status": True, "message": "Password reset link would be sent to your email."}


#======================AdminDashboard============

@app.get("/admin_stats")
def get_admin_stats():
    try:
        total_prompts = prompt_collection.count_documents({})
        total_resumes = logs_collection.count_documents({})

        if total_resumes > 0:
            logs = list(logs_collection.find({}, {"response_time": 1, "success": 1}))

            # Calculate average response time
            avg_time = sum([log.get("response_time", 0) for log in logs]) / total_resumes

            # Calculate success rate based on logs
            success_count = sum(1 for log in logs if log.get("success") is True)
            success_rate = (success_count / total_resumes) * 100
        else:
            avg_time = 0
            success_rate = 0

        return {
            "total_prompts": total_prompts,
            "resumes_analyzed": total_resumes,
            "avg_response_time": f"{round(avg_time, 2)}s",
            "success_rate": f"{round(success_rate, 1)}%"
        }

    except Exception as e:
        return {"error": str(e)}
        
#===============DataBaseLogic=================

def initialize_prompts():
    if prompt_collection.count_documents({}) == 0:
        prompts = [
            {"prompt_id": 1, "prompt_text": "Based on the candidate of a {age}-year-old student pursuing {course} in {specialization}, aiming for a career as a {career_goal}. So give them some suggestion if their resume is for another domain"},
            {"prompt_id": 2, "prompt_text": "Identify skills of the candidate from the following list, suggest improvements to highlight key strengths."},
            {"prompt_id": 3, "prompt_text": "Evaluate resume clarity, structure, and formatting. Point out any issues or improvements to make it more professional."}
        ]
        prompt_collection.insert_many(prompts)

def get_prompts_from_db():
    return [doc["prompt_text"] for doc in prompt_collection.find().sort("prompt_id", 1)]

# Initialize lite prompts
def initialize_lite_prompts():
    if lite_prompts_collection.count_documents({}) == 0:
        prompts = [
            {"prompt_id": 1, "prompt_text": "Analyze this resume for a candidate targeting {career_goal} position. Identify key strengths and weaknesses."},
            {"prompt_id": 2, "prompt_text": "Evaluate how well this resume aligns with typical requirements for {career_goal} roles."},
            {"prompt_id": 3, "prompt_text": "Provide concise suggestions to improve this resume for {career_goal} applications."}
        ]
        lite_prompts_collection.insert_many(prompts)

# ================ MAIN ROUTES ===================

@app.post("/evaluate_lite")
async def evaluate_resume_lite(
    base64_pdf: str = Form(...),
    career_goal: str = Form("")
):
    try:
        start_time = time.time()

        pdf_bytes = base64.b64decode(base64_pdf)
        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        first_page = pdf_doc[0].get_pixmap()
        img_byte_arr = io.BytesIO(first_page.tobytes("jpeg"))
        image_base64 = base64.b64encode(img_byte_arr.getvalue()).decode()
    except Exception as e:
        return {"error": f"PDF processing failed: {str(e)}"}

    prompts = [doc["prompt_text"] for doc in lite_prompts_collection.find().sort("prompt_id", 1)]
    if len(prompts) < 3:
        return {"error": "Not enough prompts in lite prompts database."}

    try:
        master_prompt = f"""
You are a career coach analyzing a resume for someone targeting {career_goal} roles.

1. {prompts[0].format(career_goal=career_goal)}
2. {prompts[1].format(career_goal=career_goal)}
3. {prompts[2].format(career_goal=career_goal)}
"""
    except KeyError as e:
        return {"error": f"Missing placeholder in prompt: {e}"}

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content([
            "Analyze this resume carefully:",
            {"mime_type": "image/jpeg", "data": image_base64},
            master_prompt
        ])
        response_text = response.text
        end_time = time.time()

        # Save analysis log
        logs_collection.insert_one({
            "career_goal": career_goal,
            "version": "lite",
            "response_time": round(end_time - start_time, 2),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "success": True
        })
    except Exception as e:
        return {"error": f"Gemini API error: {str(e)}"}

    return {"response": response_text}

@app.post("/evaluate")
async def evaluate_resume(
    base64_pdf: str = Form(...),
    age: str = Form(""),
    course: str = Form(""),
    specialization: str = Form(""),
    career_goal: str = Form("")
):
    try:
        start_time = time.time()

        pdf_bytes = base64.b64decode(base64_pdf)
        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        first_page = pdf_doc[0].get_pixmap()
        img_byte_arr = io.BytesIO(first_page.tobytes("jpeg"))
        image_base64 = base64.b64encode(img_byte_arr.getvalue()).decode()
    except Exception as e:
        return {"error": f"PDF processing failed: {str(e)}"}

    prompts = get_prompts_from_db()
    if len(prompts) < 3:
        return {"error": "Not enough prompts in database."}

    try:
        prompt1_template = prompts[0]
        prompt1 = prompt1_template.format(
            age=age,
            course=course,
            specialization=specialization,
            career_goal=career_goal
        )
    except KeyError as e:
        return {"error": f"Missing placeholder in prompt1: {e}"}

    master_prompt = f"""
You are a highly skilled HR professional, career coach, and ATS expert.

1. {prompt1}
2. {prompts[1]}
3. {prompts[2]}
"""

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content([
            "Analyze this resume carefully:",
            {"mime_type": "image/jpeg", "data": image_base64},
            master_prompt
        ])
        response_text = response.text
        end_time = time.time()

        # ✅ Save analysis log
        logs_collection.insert_one({
            "age": age,
            "course": course,
            "specialization": specialization,
            "career_goal": career_goal,
            "response_time": round(end_time - start_time, 2),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "success": True  # ✅ Add this line
        })
    except Exception as e:
        return {"error": f"Gemini API error: {str(e)}"}

    return {"response": response_text}



#=============UpdatingPrompt===================

class PromptUpdate(BaseModel):
    prompt_text: str
    prompt_id: int

@app.post("/update_prompt")
async def update_prompt(data: PromptUpdate, request: Request):
    try:
        result = prompt_collection.update_one(
            {"prompt_id": int(data.prompt_id)},
            {"$set": {"prompt_text": data.prompt_text}}
        )
        if result.modified_count == 1:
            return {"status": True}
        return {"status": False, "error": "Prompt not found or unchanged."}
    except Exception as e:
        return {"status": False, "error": str(e)}

@app.get("/debug_prompts")
async def debug_prompts():
    try:
        prompts = list(prompt_collection.find({}, {"prompt_id": 1, "prompt_text": 1, "_id": 0}))
        return {"prompts": prompts}
    except Exception as e:
        return {"status": False, "error": str(e)}


@app.post("/update_lite_prompt")
async def update_lite_prompt(data: PromptUpdate, request: Request):
    try:
        result = lite_prompts_collection.update_one(
            {"prompt_id": int(data.prompt_id)},
            {"$set": {"prompt_text": data.prompt_text}}
        )
        if result.modified_count == 1:
            return {"status": True}
        return {"status": False, "error": "Prompt not found or unchanged."}
    except Exception as e:
        return {"status": False, "error": str(e)}

@app.get("/debug_lite_prompts")
async def debug_lite_prompts():
    try:
        prompts = list(lite_prompts_collection.find({}, {"prompt_id": 1, "prompt_text": 1, "_id": 0}))
        return {"prompts": prompts}
    except Exception as e:
        return {"status": False, "error": str(e)}


# ================ INIT ============================
initialize_prompts()
initialize_lite_prompts()

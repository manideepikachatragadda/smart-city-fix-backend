import os
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime, timedelta, timezone
from config import settings

client = OpenAI(base_url=settings.OPENAI_BASE_URL, api_key=settings.OPENAI_API_KEY)

class ComplaintAnalysis(BaseModel):
    nlp_category: Literal["water", "electricity", "cleanliness", "infrastructure", "others"]
    priority_level: Literal["high", "medium", "low"]
    priority_score: int = Field(ge=1, le=10)
    sla_hours: int = Field(description="Estimated hours to resolve this issue.")

def process_complaint_ai(description: str) -> ComplaintAnalysis:
    prompt = f"Description: {description}"
    
    response = client.beta.chat.completions.parse(
        model=settings.MODEL_NAME,
        messages=[
            {"role": "system", "content": "Analyze complaint, assign department, determine priority, and estimate SLA hours."},
            {"role": "user", "content": prompt}
        ],
        response_format=ComplaintAnalysis,
        temperature=0.2
    )
    return response.choices[0].message.parsed

def calculate_sla_deadline(hours: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)
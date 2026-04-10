from openai import AsyncOpenAI  # Swapped to the Async client
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime, timedelta, timezone
from config import settings

# 1. Initialize the AsyncOpenAI client
client = AsyncOpenAI(base_url=settings.OPENAI_BASE_URL, api_key=settings.OPENAI_API_KEY)

class ComplaintAnalysis(BaseModel):
    nlp_category: Literal["water", "electricity", "sanitation", "infrastructure", "police", "fire", "others"]
    priority_level: Literal["high", "medium", "low"]
    priority_score: int = Field(ge=1, le=10)
    sla_hours: int = Field(description="Estimated hours to resolve this issue.")

# 2. Change to async def
async def process_complaint_ai(description: str) -> ComplaintAnalysis:
    prompt = f"Description: {description}"
    
    # 3. Await the async network call to the LLM
    response = await client.beta.chat.completions.parse(
        model=settings.MODEL_NAME,
        messages=[
            {"role": "system", "content": "Analyze complaint, assign department, determine priority, and estimate SLA hours."},
            {"role": "user", "content": prompt}
        ],
        response_format=ComplaintAnalysis,
        temperature=0.2
    )
    return response.choices[0].message.parsed

# This stays sync because it is just instant local math (no network or file I/O)
def calculate_sla_deadline(hours: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)
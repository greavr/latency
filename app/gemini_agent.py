import os
import json
import logging
from google import genai
from google.genai import types # <-- Import types for tool configuration

logger = logging.getLogger("latency_app")

# --- Gemini Initialization ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    logger.warning("GEMINI_API_KEY not found. Chat agent will be disabled.")
    ai_client = None

async def generate_chat_response(message: str, latest_matrix: dict) -> str:
    """Takes a user message and the current latency matrix, returns Gemini's text response."""
    if not ai_client:
        return "The Gemini API key is not configured on this server."

    system_prompt = f"""
    You are a cloud network engineering assistant. You help users analyze the current latency between Google Cloud Platform (GCP) regions.
    Use the following real-time latency matrix (in milliseconds) to answer the user's question. 
    If they ask about a region not in this list, inform them there is no active probe there.
    Keep your answers concise, helpful, and formatted in markdown.
    
    Current Latency Matrix (ms):
    {json.dumps(latest_matrix, indent=2)}
    """

    try:
        # 1. Define the Google Search tool
        search_tool = types.Tool(
            google_search=types.GoogleSearch()
        )
        
        # 2. Add it to the generation config
        config = types.GenerateContentConfig(
            tools=[search_tool],
            temperature=0.7 # Optional: slightly lower temperature for more factual responses
        )

        # 3. Pass the config to the API call
        response = await ai_client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"{system_prompt}\n\nUser Question: {message}",
            config=config
        )
        return response.text
        
    except Exception as e:
        logger.error(f"Gemini API Error: {e}", exc_info=True)
        return "Sorry, I encountered an error while trying to analyze the network data."
import os
from dotenv import load_dotenv
from app import ask_gemini_sport_assistant

# Load env vars
load_dotenv()

def test_rag():
    print("Testing RAG integration...")
    
    # Mock profile
    profile = {"height": 175, "weight": 70, "goal": "健康"}
    
    # Question about specific data in gym_info.txt
    question = "請問健身房平日幾點開？"
    
    print(f"Question: {question}")
    response = ask_gemini_sport_assistant(question, profile)
    
    print("\nResponse:")
    print(response)
    
    # Check if response contains the specific info (6:00)
    if "6:00" in response or "6點" in response:
        print("\n[SUCCESS] RAG seems to be working! Found opening time.")
    else:
        print("\n[WARNING] RAG might not be working. Opening time not found.")

if __name__ == "__main__":
    test_rag()

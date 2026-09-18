import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq(api_key=os.getenv("LLM_API_KEY"))
print(client.chat.completions.create(model=os.getenv("LLM_MODEL"), messages=[{"role": "user", "content": "I want to build a mutimodel agentic ai cli based tool for vibe coding that use groq free limits."}]).choices[0].message.content)
import os
import json

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

with open("prompt.txt", "r", encoding="utf-8") as file:
    prompt = file.read()

client = Groq(api_key=os.getenv("LLM_API_KEY"))

response = client.chat.completions.create(
    model=os.getenv("LLM_MODEL"),
    messages=[
        {
            "role": "user",
            "content": prompt
        }
    ],
)

content = response.choices[0].message.content

print(content)

print("RAW CONTENT:")
print(repr(content))

if not content:
    raise ValueError("LLM returned an empty response")


with open("output.txt", "w", encoding="utf-8") as file:
    file.write(content)

print("File Saved Successfully")
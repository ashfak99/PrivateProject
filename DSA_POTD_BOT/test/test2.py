import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

skills=["Node.js","Express","Mongodb","SQL","Git/Github","Postman","Redis"]

with open("prompt2.txt","r",encoding="utf-8") as file:
    prompt=file.read()

prompt=prompt.replace("{name}","Ashfak").replace("{email}","ashfak@gmail.com").replace("{skills}",",".join(skills))

client = Groq(api_key=os.getenv("LLM_API_KEY"))

response=client.chat.completions.create(
    model=os.getenv("LLM_MODEL"),
    messages=[
        {
            "role" : "user",
            "content" : prompt
        }
    ]
)

content=response.choices[0].message.content

with open("output2.txt","w",encoding="utf-8") as file:
    file.write(content)

print("msg written successfully")